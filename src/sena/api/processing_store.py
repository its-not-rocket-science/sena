from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


class ProcessingStore:
    def __init__(self, sqlite_path: str) -> None:
        self.sqlite_path = str(Path(sqlite_path).expanduser().resolve())
        self._lock = threading.Lock()
        self._initialize()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    key TEXT PRIMARY KEY,
                    response_json TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dead_letter_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_json TEXT NOT NULL,
                    error TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    next_retry_at TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    last_error TEXT,
                    processed_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS decision_explanations (
                    decision_id TEXT PRIMARY KEY,
                    explanation_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS governed_payloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL,
                    region TEXT NOT NULL,
                    payload_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    redacted_payload_json TEXT NOT NULL,
                    pii_flags_json TEXT NOT NULL,
                    legal_hold INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS data_access_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT,
                    tenant_id TEXT,
                    region TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def record_data_access_event(
        self,
        *,
        event_type: str,
        entity_type: str,
        entity_id: str | None = None,
        tenant_id: str | None = None,
        region: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO data_access_events(
                    event_type, entity_type, entity_id, tenant_id, region, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_type,
                    entity_type,
                    entity_id,
                    tenant_id,
                    region,
                    json.dumps(metadata or {}, sort_keys=True),
                    now,
                ),
            )
            return int(cur.lastrowid)

    def get_idempotency_response(self, key: str) -> str | None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._conn() as conn:
            row = conn.execute(
                """
                SELECT response_json
                FROM idempotency_keys
                WHERE key = ? AND expires_at > ?
                """,
                (key, now),
            ).fetchone()
        hit = row is not None
        self.record_data_access_event(
            event_type="read",
            entity_type="idempotency_key",
            entity_id=key,
            metadata={"cache_hit": hit},
        )
        return str(row["response_json"]) if row else None

    def store_idempotency_response(
        self, key: str, response_json: str, *, ttl_hours: int
    ) -> None:
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(hours=ttl_hours)).isoformat()
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO idempotency_keys(key, response_json, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (key, response_json, expires_at, now.isoformat()),
            )
        self.record_data_access_event(
            event_type="write",
            entity_type="idempotency_key",
            entity_id=key,
            metadata={"ttl_hours": ttl_hours},
        )

    def enqueue_dead_letter(self, event: dict[str, Any], error: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO dead_letter_queue(event_json, error, created_at, next_retry_at, status, last_error)
                VALUES (?, ?, ?, ?, 'pending', ?)
                """,
                (json.dumps(event, sort_keys=True), error, now, now, error),
            )
            return int(cur.lastrowid)

    def list_dead_letters(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, event_json, error, created_at, retry_count, next_retry_at, status, last_error, processed_at
                FROM dead_letter_queue
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def fetch_due_dead_letters(self, *, limit: int = 10) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, event_json, retry_count
                FROM dead_letter_queue
                WHERE status IN ('pending', 'retrying')
                  AND (next_retry_at IS NULL OR next_retry_at <= ?)
                ORDER BY id ASC
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_dead_letter_success(self, dlq_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                UPDATE dead_letter_queue
                SET status = 'succeeded', processed_at = ?
                WHERE id = ?
                """,
                (now, dlq_id),
            )

    def mark_dead_letter_failure(self, dlq_id: int, error: str) -> tuple[int, bool]:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT retry_count FROM dead_letter_queue WHERE id = ?",
                (dlq_id,),
            ).fetchone()
            if row is None:
                return 0, True
            retry_count = int(row["retry_count"]) + 1
            terminal = retry_count >= 10
            if terminal:
                conn.execute(
                    """
                    UPDATE dead_letter_queue
                    SET retry_count = ?, status = 'failed', last_error = ?
                    WHERE id = ?
                    """,
                    (retry_count, error, dlq_id),
                )
            else:
                backoff_seconds = min(2**retry_count, 300)
                next_retry = (
                    datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)
                ).isoformat()
                conn.execute(
                    """
                    UPDATE dead_letter_queue
                    SET retry_count = ?, status = 'retrying', next_retry_at = ?, last_error = ?
                    WHERE id = ?
                    """,
                    (retry_count, next_retry, error, dlq_id),
                )
        return retry_count, terminal

    def force_retry(self, ids: list[int] | None = None) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._conn() as conn:
            if ids:
                updated = 0
                for dlq_id in ids:
                    cur = conn.execute(
                        """
                        UPDATE dead_letter_queue
                        SET status = 'pending', next_retry_at = ?
                        WHERE id = ?
                        """,
                        (now, dlq_id),
                    )
                    updated += int(cur.rowcount)
                return updated
            else:
                cur = conn.execute(
                    """
                    UPDATE dead_letter_queue
                    SET status = 'pending', next_retry_at = ?
                    WHERE status IN ('failed', 'retrying', 'pending')
                    """,
                    (now,),
                )
            return int(cur.rowcount)

    def store_decision_explanation(
        self, decision_id: str, explanation: dict[str, Any]
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO decision_explanations(decision_id, explanation_json, created_at)
                VALUES (?, ?, ?)
                """,
                (decision_id, json.dumps(explanation, sort_keys=True), now),
            )
        self.record_data_access_event(
            event_type="write",
            entity_type="decision_explanation",
            entity_id=decision_id,
        )

    def get_decision_explanation(self, decision_id: str) -> dict[str, Any] | None:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                """
                SELECT explanation_json
                FROM decision_explanations
                WHERE decision_id = ?
                """,
                (decision_id,),
            ).fetchone()
        self.record_data_access_event(
            event_type="read",
            entity_type="decision_explanation",
            entity_id=decision_id,
            metadata={"exists": row is not None},
        )
        if row is None:
            return None
        return json.loads(str(row["explanation_json"]))

    def store_governed_payload(
        self,
        *,
        tenant_id: str,
        region: str,
        payload_type: str,
        payload: dict[str, Any],
        redacted_payload: dict[str, Any],
        pii_flags: list[str],
        ttl_hours: int,
    ) -> int:
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(hours=ttl_hours)).isoformat()
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO governed_payloads(
                    tenant_id, region, payload_type, payload_json, redacted_payload_json,
                    pii_flags_json, legal_hold, created_at, expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    tenant_id,
                    region,
                    payload_type,
                    json.dumps(payload, sort_keys=True),
                    json.dumps(redacted_payload, sort_keys=True),
                    json.dumps(sorted(pii_flags)),
                    now.isoformat(),
                    expires_at,
                ),
            )
            payload_id = int(cur.lastrowid)
        self.record_data_access_event(
            event_type="write",
            entity_type="governed_payload",
            entity_id=str(payload_id),
            tenant_id=tenant_id,
            region=region,
            metadata={"payload_type": payload_type, "pii_flag_count": len(pii_flags)},
        )
        return payload_id

    def list_governed_payloads(
        self, *, tenant_id: str, region: str, include_expired: bool = False
    ) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        query = """
            SELECT id, tenant_id, region, payload_type, redacted_payload_json, pii_flags_json,
                   legal_hold, created_at, expires_at
            FROM governed_payloads
            WHERE tenant_id = ? AND region = ?
        """
        params: list[Any] = [tenant_id, region]
        if not include_expired:
            query += " AND expires_at > ?"
            params.append(now)
        query += " ORDER BY id DESC"
        with self._lock, self._conn() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        self.record_data_access_event(
            event_type="read",
            entity_type="governed_payload",
            tenant_id=tenant_id,
            region=region,
            metadata={"rows": len(rows), "include_expired": include_expired},
        )
        return [dict(row) for row in rows]

    def apply_governed_payload_legal_hold(self, payload_id: int, *, reason: str) -> bool:
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE governed_payloads
                SET legal_hold = 1
                WHERE id = ?
                """,
                (payload_id,),
            )
            updated = int(cur.rowcount) > 0
        self.record_data_access_event(
            event_type="legal_hold",
            entity_type="governed_payload",
            entity_id=str(payload_id),
            metadata={"reason": reason, "updated": updated},
        )
        return updated

    def purge_expired_governed_payloads(self) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """
                DELETE FROM governed_payloads
                WHERE expires_at <= ? AND legal_hold = 0
                """,
                (now,),
            )
            deleted = int(cur.rowcount)
        if deleted:
            self.record_data_access_event(
                event_type="retention_purge",
                entity_type="governed_payload",
                metadata={"deleted": deleted},
            )
        return deleted

    def list_data_access_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, event_type, entity_type, entity_id, tenant_id, region, metadata_json, created_at
                FROM data_access_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]


@dataclass
class DeadLetterWorker:
    store: ProcessingStore
    processor: Callable[[dict[str, Any]], dict[str, Any]]
    alert_callback: Callable[[str], None]
    poll_interval_seconds: float = 0.5

    def __post_init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)

    def run_once(self) -> int:
        processed = 0
        for row in self.store.fetch_due_dead_letters(limit=10):
            processed += 1
            dlq_id = int(row["id"])
            event = json.loads(str(row["event_json"]))
            try:
                self.processor(event)
            except Exception as exc:  # pragma: no cover
                retry_count, terminal = self.store.mark_dead_letter_failure(
                    dlq_id, str(exc)
                )
                if terminal:
                    self.alert_callback(
                        f"dead_letter_queue event {dlq_id} exhausted retries={retry_count}: {exc}"
                    )
            else:
                self.store.mark_dead_letter_success(dlq_id)
        return processed

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception:  # pragma: no cover
                logger.exception("dead-letter worker loop failed")
            time.sleep(self.poll_interval_seconds)
