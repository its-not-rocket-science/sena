from __future__ import annotations

from sena.services.reliability_service import (
    CircuitBreaker,
    InMemoryIngestionQueue,
    ReliabilityService,
    SQLiteIngestionQueue,
)


class _ManualClockBreaker(CircuitBreaker):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._t = 0.0

    def _now(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


def test_in_memory_ingestion_queue_buffers_events_fifo() -> None:
    service = ReliabilityService(ingestion_queue=InMemoryIngestionQueue(max_size=2))
    service.enqueue_event({"id": 1})
    service.enqueue_event({"id": 2})

    assert service.process_next(lambda event: event)["id"] == 1
    assert service.process_next(lambda event: event)["id"] == 2
    assert service.process_next(lambda event: event)["status"] == "empty"


def test_circuit_breaker_fails_fast_after_threshold() -> None:
    breaker = _ManualClockBreaker(failure_threshold=2, recovery_timeout_seconds=10)
    service = ReliabilityService(
        ingestion_queue=InMemoryIngestionQueue(max_size=1),
        circuit_breakers={"jira": breaker},
    )

    first = service.call_dependency(
        dependency_name="jira",
        operation=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        fallback=lambda reason: {"reason": reason},
    )
    second = service.call_dependency(
        dependency_name="jira",
        operation=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        fallback=lambda reason: {"reason": reason},
    )
    assert first["reason"] == "dependency_failure"
    assert second["reason"] == "dependency_failure"
    assert breaker.state == "open"

    fast_fail = service.call_dependency(
        dependency_name="jira",
        operation=lambda: {"status": "ok"},
        fallback=lambda reason: {"reason": reason},
    )
    assert fast_fail["reason"] == "circuit_open"

    breaker.advance(11)
    recovered = service.call_dependency(
        dependency_name="jira",
        operation=lambda: {"status": "ok"},
        fallback=lambda reason: {"reason": reason},
    )
    assert recovered["status"] == "ok"
    assert breaker.state == "closed"


def test_sqlite_ingestion_queue_survives_restart_for_unprocessed_events(tmp_path) -> None:
    db_path = tmp_path / "ingestion-queue.db"
    first = ReliabilityService(
        ingestion_queue=SQLiteIngestionQueue(sqlite_path=str(db_path))
    )
    first.enqueue_event({"id": "event-1", "payload": {"x": 1}})

    second = ReliabilityService(
        ingestion_queue=SQLiteIngestionQueue(sqlite_path=str(db_path))
    )
    assert second.process_next(lambda event: event) == {
        "id": "event-1",
        "payload": {"x": 1},
    }
    assert second.process_next(lambda event: event) == {"status": "empty"}
