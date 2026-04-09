from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class SQLiteAppendOnlyAuditSink:
    sqlite_path: str
    table_name: str = "audit_log"

    def _connect(self) -> sqlite3.Connection:
        Path(self.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.sqlite_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        self._ensure_schema(conn)
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                storage_sequence_number INTEGER PRIMARY KEY AUTOINCREMENT,
                write_timestamp TEXT NOT NULL,
                decision_id TEXT,
                chain_hash TEXT NOT NULL,
                previous_chain_hash TEXT,
                payload_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS {self.table_name}_deny_update
            BEFORE UPDATE ON {self.table_name}
            BEGIN
                SELECT RAISE(ABORT, 'append-only table: updates are forbidden');
            END
            """
        )
        conn.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS {self.table_name}_deny_delete
            BEFORE DELETE ON {self.table_name}
            BEGIN
                SELECT RAISE(ABORT, 'append-only table: deletes are forbidden');
            END
            """
        )
        conn.commit()

    def load_records(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT storage_sequence_number, payload_json FROM {self.table_name} ORDER BY storage_sequence_number"
            ).fetchall()
        result: list[dict[str, Any]] = []
        for seq, payload_json in rows:
            payload = json.loads(payload_json)
            payload["storage_sequence_number"] = int(seq)
            result.append(payload)
        return result

    def append(self, payload: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {self.table_name}
                (write_timestamp, decision_id, chain_hash, previous_chain_hash, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(payload.get("write_timestamp") or datetime.now(tz=timezone.utc).isoformat()),
                    payload.get("decision_id"),
                    payload.get("chain_hash"),
                    payload.get("previous_chain_hash"),
                    json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str),
                ),
            )
            conn.commit()

    def append_chained(self, payload: dict[str, Any], compute_hash) -> dict[str, Any]:
        with self._connect() as conn:
            previous = conn.execute(
                f"SELECT storage_sequence_number, chain_hash FROM {self.table_name} ORDER BY storage_sequence_number DESC LIMIT 1"
            ).fetchone()
            previous_chain_hash = previous[1] if previous else None
            line = dict(payload)
            line["write_timestamp"] = datetime.now(tz=timezone.utc).isoformat()
            line["previous_chain_hash"] = previous_chain_hash
            record_for_hash = {k: v for k, v in line.items() if k != "chain_hash"}
            line["chain_hash"] = compute_hash(record_for_hash, previous_chain_hash)
            cursor = conn.execute(
                f"""
                INSERT INTO {self.table_name}
                (write_timestamp, decision_id, chain_hash, previous_chain_hash, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    line["write_timestamp"],
                    line.get("decision_id"),
                    line["chain_hash"],
                    line.get("previous_chain_hash"),
                    json.dumps(line, sort_keys=True, separators=(",", ":"), default=str),
                ),
            )
            seq = int(cursor.lastrowid)
            conn.commit()
        line["storage_sequence_number"] = seq
        return line
