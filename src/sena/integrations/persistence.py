from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sena.integrations.approval import DeadLetterItem


@dataclass(frozen=True)
class DeliveryCompletionRecord:
    operation_key: str
    target: str
    completed_at: str
    attempts: int
    max_attempts: int
    payload: dict[str, Any]
    result: dict[str, Any] | None


@dataclass(frozen=True)
class OutboundDeadLetterRecord:
    id: int
    operation_key: str
    target: str
    error: str
    attempts: int
    max_attempts: int | None
    first_failed_at: str | None
    last_failed_at: str | None
    payload: dict[str, Any]
    created_at: str


class SQLiteIntegrationReliabilityStore:
    """Durable SQLite-backed stores for connector reliability state."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = FULL")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS delivery_idempotency_keys (
                    delivery_id TEXT PRIMARY KEY,
                    observed_at TEXT NOT NULL,
                    last_seen_at TEXT,
                    seen_count INTEGER NOT NULL DEFAULT 1,
                    suppressed_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS outbound_delivery_completion (
                    operation_key TEXT PRIMARY KEY,
                    target TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    result_json TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS outbound_delivery_dead_letter (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation_key TEXT NOT NULL,
                    target TEXT NOT NULL,
                    error TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    max_attempts INTEGER,
                    first_failed_at TEXT,
                    last_failed_at TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS outbound_delivery_duplicate_suppression (
                    operation_key TEXT PRIMARY KEY,
                    target TEXT NOT NULL,
                    first_suppressed_at TEXT NOT NULL,
                    last_suppressed_at TEXT NOT NULL,
                    suppressed_count INTEGER NOT NULL
                )
                """
            )
            columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(delivery_idempotency_keys)")
            }
            if "last_seen_at" not in columns:
                conn.execute(
                    "ALTER TABLE delivery_idempotency_keys ADD COLUMN last_seen_at TEXT"
                )
            if "seen_count" not in columns:
                conn.execute(
                    "ALTER TABLE delivery_idempotency_keys ADD COLUMN seen_count INTEGER NOT NULL DEFAULT 1"
                )
            if "suppressed_count" not in columns:
                conn.execute(
                    "ALTER TABLE delivery_idempotency_keys ADD COLUMN suppressed_count INTEGER NOT NULL DEFAULT 0"
                )

    def mark_if_new(self, delivery_id: str) -> bool:
        observed_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT seen_count, suppressed_count FROM delivery_idempotency_keys WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO delivery_idempotency_keys (
                        delivery_id, observed_at, last_seen_at, seen_count, suppressed_count
                    )
                    VALUES (?, ?, ?, 1, 0)
                    """,
                    (delivery_id, observed_at, observed_at),
                )
                return True
            conn.execute(
                """
                UPDATE delivery_idempotency_keys
                SET last_seen_at = ?, seen_count = ?, suppressed_count = ?
                WHERE delivery_id = ?
                """,
                (
                    observed_at,
                    int(existing["seen_count"]) + 1,
                    int(existing["suppressed_count"]) + 1,
                    delivery_id,
                ),
            )
            return False

    def mark_completed(
        self,
        operation_key: str,
        *,
        target: str,
        payload: dict[str, Any],
        result: dict[str, Any] | None,
        attempts: int,
        max_attempts: int,
    ) -> None:
        completed_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO outbound_delivery_completion (
                    operation_key,
                    target,
                    completed_at,
                    attempts,
                    max_attempts,
                    payload_json,
                    result_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_key,
                    target,
                    completed_at,
                    attempts,
                    max_attempts,
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    json.dumps(result, sort_keys=True, separators=(",", ":"))
                    if result is not None
                    else None,
                ),
            )

    def has_completed(self, operation_key: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM outbound_delivery_completion WHERE operation_key = ?",
                (operation_key,),
            ).fetchone()
            return row is not None

    def get_completion(self, operation_key: str) -> DeliveryCompletionRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM outbound_delivery_completion WHERE operation_key = ?",
                (operation_key,),
            ).fetchone()
        if row is None:
            return None
        result_raw = row["result_json"]
        return DeliveryCompletionRecord(
            operation_key=str(row["operation_key"]),
            target=str(row["target"]),
            completed_at=str(row["completed_at"]),
            attempts=int(row["attempts"]),
            max_attempts=int(row["max_attempts"]),
            payload=json.loads(str(row["payload_json"])),
            result=json.loads(result_raw) if result_raw else None,
        )

    def push(self, item: DeadLetterItem) -> None:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO outbound_delivery_dead_letter (
                    operation_key,
                    target,
                    error,
                    attempts,
                    max_attempts,
                    first_failed_at,
                    last_failed_at,
                    payload_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.operation_key,
                    item.target,
                    item.error,
                    item.attempts,
                    item.max_attempts,
                    item.first_failed_at,
                    item.last_failed_at,
                    json.dumps(item.payload, sort_keys=True, separators=(",", ":")),
                    created_at,
                ),
            )

    def record_outbound_duplicate_suppression(
        self, *, operation_key: str, target: str
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT suppressed_count, first_suppressed_at
                FROM outbound_delivery_duplicate_suppression
                WHERE operation_key = ?
                """,
                (operation_key,),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO outbound_delivery_duplicate_suppression (
                        operation_key, target, first_suppressed_at, last_suppressed_at, suppressed_count
                    )
                    VALUES (?, ?, ?, ?, 1)
                    """,
                    (operation_key, target, now, now),
                )
                return
            conn.execute(
                """
                UPDATE outbound_delivery_duplicate_suppression
                SET last_suppressed_at = ?, suppressed_count = ?
                WHERE operation_key = ?
                """,
                (now, int(row["suppressed_count"]) + 1, operation_key),
            )

    def items(self) -> list[DeadLetterItem]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT operation_key, target, error, attempts, max_attempts,
                       first_failed_at, last_failed_at, payload_json
                FROM outbound_delivery_dead_letter
                ORDER BY id ASC
                """
            ).fetchall()
        return [
            DeadLetterItem(
                operation_key=str(row["operation_key"]),
                target=str(row["target"]),
                error=str(row["error"]),
                attempts=int(row["attempts"]),
                payload=json.loads(str(row["payload_json"])),
                max_attempts=(
                    int(row["max_attempts"]) if row["max_attempts"] is not None else None
                ),
                first_failed_at=(
                    str(row["first_failed_at"])
                    if row["first_failed_at"] is not None
                    else None
                ),
                last_failed_at=(
                    str(row["last_failed_at"])
                    if row["last_failed_at"] is not None
                    else None
                ),
            )
            for row in rows
        ]

    def list_completion_records(self, *, limit: int = 100) -> list[DeliveryCompletionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM outbound_delivery_completion
                ORDER BY completed_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            DeliveryCompletionRecord(
                operation_key=str(row["operation_key"]),
                target=str(row["target"]),
                completed_at=str(row["completed_at"]),
                attempts=int(row["attempts"]),
                max_attempts=int(row["max_attempts"]),
                payload=json.loads(str(row["payload_json"])),
                result=(
                    json.loads(str(row["result_json"]))
                    if row["result_json"] is not None
                    else None
                ),
            )
            for row in rows
        ]

    def list_dead_letter_records(self, *, limit: int = 100) -> list[OutboundDeadLetterRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, operation_key, target, error, attempts, max_attempts,
                       first_failed_at, last_failed_at, payload_json, created_at
                FROM outbound_delivery_dead_letter
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            OutboundDeadLetterRecord(
                id=int(row["id"]),
                operation_key=str(row["operation_key"]),
                target=str(row["target"]),
                error=str(row["error"]),
                attempts=int(row["attempts"]),
                max_attempts=(
                    int(row["max_attempts"]) if row["max_attempts"] is not None else None
                ),
                first_failed_at=(
                    str(row["first_failed_at"])
                    if row["first_failed_at"] is not None
                    else None
                ),
                last_failed_at=(
                    str(row["last_failed_at"]) if row["last_failed_at"] is not None else None
                ),
                payload=json.loads(str(row["payload_json"])),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def get_dead_letter_record(self, dead_letter_id: int) -> OutboundDeadLetterRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, operation_key, target, error, attempts, max_attempts,
                       first_failed_at, last_failed_at, payload_json, created_at
                FROM outbound_delivery_dead_letter
                WHERE id = ?
                """,
                (dead_letter_id,),
            ).fetchone()
        if row is None:
            return None
        return OutboundDeadLetterRecord(
            id=int(row["id"]),
            operation_key=str(row["operation_key"]),
            target=str(row["target"]),
            error=str(row["error"]),
            attempts=int(row["attempts"]),
            max_attempts=int(row["max_attempts"]) if row["max_attempts"] is not None else None,
            first_failed_at=str(row["first_failed_at"]) if row["first_failed_at"] is not None else None,
            last_failed_at=str(row["last_failed_at"]) if row["last_failed_at"] is not None else None,
            payload=json.loads(str(row["payload_json"])),
            created_at=str(row["created_at"]),
        )

    def delete_dead_letter_record(self, dead_letter_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM outbound_delivery_dead_letter WHERE id = ?",
                (dead_letter_id,),
            )
            return int(cursor.rowcount) == 1

    def duplicate_suppression_summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            inbound = conn.execute(
                """
                SELECT COALESCE(SUM(suppressed_count), 0) AS suppressed_total,
                       COALESCE(SUM(seen_count), 0) AS seen_total,
                       COUNT(*) AS unique_delivery_ids
                FROM delivery_idempotency_keys
                """
            ).fetchone()
            outbound = conn.execute(
                """
                SELECT COALESCE(SUM(suppressed_count), 0) AS suppressed_total,
                       COUNT(*) AS unique_operation_keys
                FROM outbound_delivery_duplicate_suppression
                """
            ).fetchone()
            outbound_by_target_rows = conn.execute(
                """
                SELECT target, COALESCE(SUM(suppressed_count), 0) AS suppressed_total
                FROM outbound_delivery_duplicate_suppression
                GROUP BY target
                ORDER BY target ASC
                """
            ).fetchall()
        return {
            "inbound": {
                "unique_delivery_ids": int(inbound["unique_delivery_ids"]),
                "seen_total": int(inbound["seen_total"]),
                "suppressed_total": int(inbound["suppressed_total"]),
            },
            "outbound": {
                "unique_operation_keys": int(outbound["unique_operation_keys"]),
                "suppressed_total": int(outbound["suppressed_total"]),
                "by_target": {
                    str(row["target"]): int(row["suppressed_total"])
                    for row in outbound_by_target_rows
                },
            },
        }
