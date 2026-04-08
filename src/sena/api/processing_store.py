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
