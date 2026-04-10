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
                    observed_at TEXT NOT NULL
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

    def mark_if_new(self, delivery_id: str) -> bool:
        observed_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO delivery_idempotency_keys (delivery_id, observed_at)
                VALUES (?, ?)
                """,
                (delivery_id, observed_at),
            )
            return int(cursor.rowcount) == 1

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
