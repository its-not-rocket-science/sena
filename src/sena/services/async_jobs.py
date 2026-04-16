from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
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
    """Simple in-process async job manager for development and single-node deployments."""

    def __init__(
        self,
        *,
        max_workers: int = 4,
        on_submitted: Callable[[str], None] | None = None,
        on_terminal: Callable[[str, str], None] | None = None,
    ):
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="sena-jobs"
        )
        self._lock = threading.RLock()
        self._jobs: dict[str, JobRecord] = {}
        self._futures: dict[str, Future[Any]] = {}
        self._on_submitted = on_submitted
        self._on_terminal = on_terminal

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
                return
            record.status = "running"
            record.started_at = self._utc_now()
            timeout_seconds = record.timeout_seconds
            started_at = datetime.now(timezone.utc)

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
                    record.result_ref = f"memory://jobs/{job_id}/result"
                record.completed_at = self._utc_now()
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
                self._emit_terminal(record)

    def _emit_terminal(self, record: JobRecord) -> None:
        if self._on_terminal is None:
            return
        self._on_terminal(record.job_type, record.status)

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
