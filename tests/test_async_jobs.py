from __future__ import annotations

import threading
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


def test_job_lifecycle_success_and_idempotent_polling(tmp_path) -> None:
    manager = InProcessJobManager(
        max_workers=1, sqlite_path=str(tmp_path / "async_jobs.db")
    )
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


def test_job_failed_payload(tmp_path) -> None:
    manager = InProcessJobManager(max_workers=1, sqlite_path=str(tmp_path / "jobs.db"))
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


def test_job_timeout_semantics(tmp_path) -> None:
    manager = InProcessJobManager(max_workers=1, sqlite_path=str(tmp_path / "jobs.db"))
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


def test_job_cancel_semantics(tmp_path) -> None:
    manager = InProcessJobManager(max_workers=1, sqlite_path=str(tmp_path / "jobs.db"))
    try:
        record = manager.submit(runner=lambda: (time.sleep(0.03), {"ok": True})[1])
        manager.cancel(record.job_id)
        status = _wait_for_terminal_status(manager, record.job_id)
        assert status == "cancelled"
    finally:
        manager.shutdown()


def test_terminal_jobs_remain_queryable_after_restart(tmp_path) -> None:
    sqlite_path = str(tmp_path / "jobs.db")
    manager = InProcessJobManager(max_workers=1, sqlite_path=sqlite_path)
    try:
        record = manager.submit(runner=lambda: {"answer": 42})
        status = _wait_for_terminal_status(manager, record.job_id)
        assert status == "succeeded"
    finally:
        manager.shutdown()

    restarted = InProcessJobManager(max_workers=1, sqlite_path=sqlite_path)
    try:
        recovered = restarted.get(record.job_id)
        assert recovered is not None
        assert recovered.status == "succeeded"
        assert recovered.result == {"answer": 42}
        assert recovered.result_ref == f"sqlite://async_jobs/{record.job_id}"
    finally:
        restarted.shutdown()


def test_inflight_job_is_marked_failed_after_restart(tmp_path) -> None:
    sqlite_path = str(tmp_path / "jobs.db")
    manager = InProcessJobManager(max_workers=1, sqlite_path=sqlite_path)
    event = threading.Event()
    try:
        record = manager.submit(
            runner=lambda: (event.wait(0.3), {"ok": True})[1], job_type="simulation"
        )
        deadline = time.time() + 1.0
        while time.time() < deadline:
            current = manager.get(record.job_id)
            assert current is not None
            if current.status == "running":
                break
            time.sleep(0.005)
        else:
            raise AssertionError("job did not start running")
    finally:
        manager.shutdown()

    restarted = InProcessJobManager(max_workers=1, sqlite_path=sqlite_path)
    try:
        recovered = restarted.get(record.job_id)
        assert recovered is not None
        assert recovered.status == "failed"
        assert recovered.error is not None
        assert recovered.error["code"] == "interrupted_by_restart"
        assert recovered.error["previous_status"] in {"queued", "running"}
    finally:
        restarted.shutdown()


def test_cancelled_job_remains_cancelled_after_restart(tmp_path) -> None:
    sqlite_path = str(tmp_path / "jobs.db")
    manager = InProcessJobManager(max_workers=1, sqlite_path=sqlite_path)
    try:
        record = manager.submit(runner=lambda: (time.sleep(0.05), {"ok": True})[1])
        manager.cancel(record.job_id)
        status = _wait_for_terminal_status(manager, record.job_id)
        assert status == "cancelled"
    finally:
        manager.shutdown()

    restarted = InProcessJobManager(max_workers=1, sqlite_path=sqlite_path)
    try:
        recovered = restarted.get(record.job_id)
        assert recovered is not None
        assert recovered.status == "cancelled"
    finally:
        restarted.shutdown()
