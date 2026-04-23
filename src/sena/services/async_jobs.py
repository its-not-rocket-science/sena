from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
import traceback
from typing import Any, Callable, Literal
from uuid import uuid4

JobStatus = Literal[
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
]
TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled", "timed_out"}


@dataclass
class JobRecord:
    job_id: str
    status: JobStatus
    submitted_at: str
    job_type: str = "generic"
    started_at: str | None = None
    completed_at: str | None = None
    result_ref: str | None = None
    error: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    timeout_seconds: float | None = None
    cancel_requested: bool = False

    def to_status_payload(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "submitted_at": self.submitted_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result_ref": self.result_ref,
            "error": self.error,
        }


class InProcessJobManager:
    """In-process async job manager with durable metadata persisted to sqlite."""

    def __init__(
        self,
        *,
        max_workers: int = 4,
        sqlite_path: str = "./.sena_runtime.db",
        on_submitted: Callable[[str], None] | None = None,
        on_terminal: Callable[[str, str], None] | None = None,
    ):
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="sena-jobs"
        )
        self._lock = threading.RLock()
        self._sqlite_path = sqlite_path
        self._jobs: dict[str, JobRecord] = {}
        self._futures: dict[str, Future[Any]] = {}
        self._on_submitted = on_submitted
        self._on_terminal = on_terminal
        self._initialize_store()
        self._load_jobs_from_store()
        self._recover_inflight_jobs()

    def submit(
        self,
        *,
        runner: Callable[[], dict[str, Any]],
        job_type: str = "generic",
        timeout_seconds: float | None = None,
    ) -> JobRecord:
        job_id = str(uuid4())
        now = self._utc_now()
        record = JobRecord(
            job_id=job_id,
            job_type=job_type,
            status="queued",
            submitted_at=now,
            timeout_seconds=timeout_seconds,
        )
        with self._lock:
            self._jobs[job_id] = record
            self._persist_job(record)
            self._futures[job_id] = self._executor.submit(self._run_job, job_id, runner)
        if self._on_submitted is not None:
            self._on_submitted(job_type)
        return record

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> JobRecord | None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return None
            if record.status in TERMINAL_JOB_STATUSES:
                return record
            record.cancel_requested = True
            future = self._futures.get(job_id)
            if future is not None and future.cancel():
                completed = self._utc_now()
                record.status = "cancelled"
                record.completed_at = completed
                record.error = {
                    "code": "cancelled",
                    "message": "job cancelled before execution",
                }
                self._persist_job(record)
                self._emit_terminal(record)
            else:
                self._persist_job(record)
            return record

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        with self._lock:
            for record in self._jobs.values():
                counts[record.status] = counts.get(record.status, 0) + 1
        return counts

    def _run_job(self, job_id: str, runner: Callable[[], dict[str, Any]]) -> None:
        with self._lock:
            record = self._jobs[job_id]
            if record.cancel_requested:
                if record.status not in TERMINAL_JOB_STATUSES:
                    record.status = "cancelled"
                    record.completed_at = self._utc_now()
                    record.error = {
                        "code": "cancelled",
                        "message": "job cancelled before execution",
                    }
                    self._persist_job(record)
                    self._emit_terminal(record)
                return
            record.status = "running"
            record.started_at = self._utc_now()
            timeout_seconds = record.timeout_seconds
            started_at = datetime.now(timezone.utc)
            self._persist_job(record)

        try:
            result = runner()
            elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
            with self._lock:
                record = self._jobs[job_id]
                if record.cancel_requested:
                    record.status = "cancelled"
                    record.error = {
                        "code": "cancelled",
                        "message": "job cancellation was requested while running",
                    }
                elif timeout_seconds is not None and elapsed > timeout_seconds:
                    record.status = "timed_out"
                    record.error = {
                        "code": "timeout",
                        "message": f"job exceeded timeout of {timeout_seconds} seconds",
                        "elapsed_seconds": round(elapsed, 3),
                    }
                else:
                    record.status = "succeeded"
                    record.result = result
                    record.result_ref = f"sqlite://async_jobs/{job_id}"
                record.completed_at = self._utc_now()
                self._persist_job(record)
                self._emit_terminal(record)
        except Exception as exc:  # pragma: no cover - exercised via API tests
            with self._lock:
                record = self._jobs[job_id]
                record.status = "failed"
                record.completed_at = self._utc_now()
                record.error = {
                    "code": "job_failed",
                    "message": str(exc),
                    "type": exc.__class__.__name__,
                    "trace": traceback.format_exc(limit=5),
                }
                self._persist_job(record)
                self._emit_terminal(record)

    def _initialize_store(self) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS async_jobs (
                    job_id TEXT PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    result_ref TEXT,
                    error_json TEXT,
                    result_json TEXT,
                    timeout_seconds REAL,
                    cancel_requested INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            columns = {
                str(row["name"]) for row in conn.execute("PRAGMA table_info(async_jobs)")
            }
            if "result_json" not in columns:
                conn.execute("ALTER TABLE async_jobs ADD COLUMN result_json TEXT")
            if "cancel_requested" not in columns:
                conn.execute(
                    "ALTER TABLE async_jobs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0"
                )

    def _load_jobs_from_store(self) -> None:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                """
                SELECT
                    job_id,
                    job_type,
                    status,
                    submitted_at,
                    started_at,
                    completed_at,
                    result_ref,
                    error_json,
                    result_json,
                    timeout_seconds,
                    cancel_requested
                FROM async_jobs
                """
            ).fetchall()
            for row in rows:
                self._jobs[str(row["job_id"])] = JobRecord(
                    job_id=str(row["job_id"]),
                    job_type=str(row["job_type"]),
                    status=str(row["status"]),
                    submitted_at=str(row["submitted_at"]),
                    started_at=str(row["started_at"]) if row["started_at"] else None,
                    completed_at=(
                        str(row["completed_at"]) if row["completed_at"] else None
                    ),
                    result_ref=str(row["result_ref"]) if row["result_ref"] else None,
                    error=(
                        json.loads(str(row["error_json"])) if row["error_json"] else None
                    ),
                    result=(
                        json.loads(str(row["result_json"]))
                        if row["result_json"]
                        else None
                    ),
                    timeout_seconds=(
                        float(row["timeout_seconds"])
                        if row["timeout_seconds"] is not None
                        else None
                    ),
                    cancel_requested=bool(row["cancel_requested"]),
                )

    def _recover_inflight_jobs(self) -> None:
        recovered_at = self._utc_now()
        with self._lock:
            for record in self._jobs.values():
                if record.status not in {"queued", "running"}:
                    continue
                previous_status = record.status
                record.status = "failed"
                record.completed_at = recovered_at
                record.error = {
                    "code": "interrupted_by_restart",
                    "message": (
                        "job was in-flight when the API restarted and was marked failed "
                        "for deterministic recovery"
                    ),
                    "previous_status": previous_status,
                }
                self._persist_job(record)

    def _persist_job(self, record: JobRecord) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT INTO async_jobs(
                    job_id,
                    job_type,
                    status,
                    submitted_at,
                    started_at,
                    completed_at,
                    result_ref,
                    error_json,
                    result_json,
                    timeout_seconds,
                    cancel_requested
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    job_type=excluded.job_type,
                    status=excluded.status,
                    submitted_at=excluded.submitted_at,
                    started_at=excluded.started_at,
                    completed_at=excluded.completed_at,
                    result_ref=excluded.result_ref,
                    error_json=excluded.error_json,
                    result_json=excluded.result_json,
                    timeout_seconds=excluded.timeout_seconds,
                    cancel_requested=excluded.cancel_requested
                """,
                (
                    record.job_id,
                    record.job_type,
                    record.status,
                    record.submitted_at,
                    record.started_at,
                    record.completed_at,
                    record.result_ref,
                    json.dumps(record.error, sort_keys=True) if record.error else None,
                    json.dumps(record.result, sort_keys=True) if record.result else None,
                    record.timeout_seconds,
                    int(record.cancel_requested),
                ),
            )

    def _conn(self) -> sqlite3.Connection:
        path = Path(self._sqlite_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        return conn

    def _emit_terminal(self, record: JobRecord) -> None:
        if self._on_terminal is None:
            return
        self._on_terminal(record.job_type, record.status)

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
