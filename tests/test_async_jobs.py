from __future__ import annotations

import time

from sena.services.async_jobs import InProcessJobManager


def _wait_for_terminal_status(
    manager: InProcessJobManager, job_id: str, timeout_seconds: float = 1.0
) -> str:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        record = manager.get(job_id)
        assert record is not None
        if record.status in {"succeeded", "failed", "cancelled", "timed_out"}:
            return record.status
        time.sleep(0.005)
    raise AssertionError(f"job '{job_id}' did not finish")


def test_job_lifecycle_success_and_idempotent_polling() -> None:
    manager = InProcessJobManager(max_workers=1)
    try:
        record = manager.submit(runner=lambda: {"answer": 42})
        status = _wait_for_terminal_status(manager, record.job_id)
        assert status == "succeeded"

        first = manager.get(record.job_id)
        second = manager.get(record.job_id)
        assert first is not None and second is not None
        assert first.to_status_payload() == second.to_status_payload()
        assert first.result == {"answer": 42}
    finally:
        manager.shutdown()


def test_job_failed_payload() -> None:
    manager = InProcessJobManager(max_workers=1)
    try:
        record = manager.submit(
            runner=lambda: (_ for _ in ()).throw(ValueError("boom"))
        )
        status = _wait_for_terminal_status(manager, record.job_id)
        assert status == "failed"

        failed = manager.get(record.job_id)
        assert failed is not None
        assert failed.error is not None
        assert failed.error["code"] == "job_failed"
        assert failed.error["type"] == "ValueError"
    finally:
        manager.shutdown()


def test_job_timeout_semantics() -> None:
    manager = InProcessJobManager(max_workers=1)
    try:
        record = manager.submit(
            runner=lambda: (time.sleep(0.03), {"ok": True})[1], timeout_seconds=0.001
        )
        status = _wait_for_terminal_status(manager, record.job_id)
        assert status == "timed_out"

        timed_out = manager.get(record.job_id)
        assert timed_out is not None
        assert timed_out.error is not None
        assert timed_out.error["code"] == "timeout"
    finally:
        manager.shutdown()


def test_job_cancel_semantics() -> None:
    manager = InProcessJobManager(max_workers=1)
    try:
        record = manager.submit(runner=lambda: (time.sleep(0.03), {"ok": True})[1])
        manager.cancel(record.job_id)
        status = _wait_for_terminal_status(manager, record.job_id)
        assert status == "cancelled"
    finally:
        manager.shutdown()
