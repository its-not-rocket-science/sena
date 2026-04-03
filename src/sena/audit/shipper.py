from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sena.audit.sinks import JsonlFileAuditSink


@dataclass
class RetryQueue:
    sqlite_path: str

    def __post_init__(self) -> None:
        self._conn().execute(
            """
            CREATE TABLE IF NOT EXISTS audit_ship_retry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                destination TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_epoch REAL NOT NULL DEFAULT 0
            )
            """
        )
        self._conn().commit()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn

    def enqueue(self, *, entry_id: str, payload: dict[str, Any], destination: str, attempts: int = 0, next_attempt_epoch: float = 0.0) -> None:
        conn = self._conn()
        conn.execute(
            "INSERT INTO audit_ship_retry(entry_id, payload_json, destination, attempts, next_attempt_epoch) VALUES (?, ?, ?, ?, ?)",
            (entry_id, json.dumps(payload, sort_keys=True), destination, attempts, next_attempt_epoch),
        )
        conn.commit()
        conn.close()

    def due_items(self, now_epoch: float) -> list[dict[str, Any]]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT id, entry_id, payload_json, destination, attempts FROM audit_ship_retry WHERE next_attempt_epoch <= ? ORDER BY id ASC",
            (now_epoch,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def remove(self, row_id: int) -> None:
        conn = self._conn()
        conn.execute("DELETE FROM audit_ship_retry WHERE id = ?", (row_id,))
        conn.commit()
        conn.close()

    def reschedule(self, row_id: int, attempts: int, next_attempt_epoch: float) -> None:
        conn = self._conn()
        conn.execute(
            "UPDATE audit_ship_retry SET attempts = ?, next_attempt_epoch = ? WHERE id = ?",
            (attempts, next_attempt_epoch, row_id),
        )
        conn.commit()
        conn.close()


@dataclass
class AuditShipper:
    audit_path: str
    destination: str
    retry_queue: RetryQueue
    state_path: str
    poll_interval_seconds: float = 1.0

    def _read_state(self) -> int:
        path = Path(self.state_path)
        if not path.exists():
            return 0
        return int(path.read_text(encoding="utf-8").strip() or "0")

    def _write_state(self, idx: int) -> None:
        path = Path(self.state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(idx), encoding="utf-8")

    def _deliver(self, payload: dict[str, Any]) -> None:
        if self.destination.startswith(("http://", "https://")):
            req = urllib.request.Request(
                self.destination,
                data=json.dumps(payload, sort_keys=True).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as response:  # nosec B310
                if response.status >= 300:
                    raise RuntimeError(f"http ship failure: {response.status}")
            return
        if self.destination.startswith("file://"):
            file_path = Path(self.destination.replace("file://", "", 1))
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with file_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, sort_keys=True) + "\n")
            return
        raise RuntimeError(f"Unsupported ship destination: {self.destination}")

    def ship_once(self) -> dict[str, Any]:
        sink = JsonlFileAuditSink(path=self.audit_path)
        rows = sink.load_records()
        cursor = self._read_state()
        sent = 0
        failed = 0

        for row in rows[cursor:]:
            entry_id = str(row.get("decision_id") or row.get("chain_hash") or "unknown")
            try:
                self._deliver(row)
                sent += 1
                cursor += 1
            except Exception:
                failed += 1
                self.retry_queue.enqueue(
                    entry_id=entry_id,
                    payload=row,
                    destination=self.destination,
                    attempts=1,
                    next_attempt_epoch=time.time() + 1,
                )
                cursor += 1

        self._write_state(cursor)
        self._drain_retry_queue()
        return {"sent": sent, "failed": failed, "cursor": cursor}

    def _drain_retry_queue(self) -> None:
        now = time.time()
        for item in self.retry_queue.due_items(now):
            row_id = int(item["id"])
            attempts = int(item["attempts"])
            payload = json.loads(str(item["payload_json"]))
            try:
                self._deliver(payload)
                self.retry_queue.remove(row_id)
            except Exception:
                next_attempt = now + min(300, 2**attempts)
                self.retry_queue.reschedule(row_id, attempts + 1, next_attempt)


def shipper_from_env(audit_path: str | None) -> AuditShipper | None:
    destination = os.getenv("SENA_AUDIT_SHIP_DESTINATION")
    if not destination or not audit_path:
        return None
    retry_db = os.getenv("SENA_AUDIT_SHIP_RETRY_DB", str(Path(audit_path).with_name("audit_ship_retry.sqlite")))
    state_path = os.getenv("SENA_AUDIT_SHIP_STATE", str(Path(audit_path).with_name("audit_ship_cursor.state")))
    return AuditShipper(
        audit_path=audit_path,
        destination=destination,
        retry_queue=RetryQueue(sqlite_path=retry_db),
        state_path=state_path,
    )
