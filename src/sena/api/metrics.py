from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest

from sena.monitoring.dashboard import TractionMetrics


class ApiMetrics:
    """Application-scoped Prometheus metrics for API monitoring."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry(auto_describe=True)
        self.traction = TractionMetrics(registry=self.registry)

    def observe_request(self, *, method: str, path: str, status_code: int) -> None:
        self.traction.observe_request(
            method=method,
            path=path,
            status_code=status_code,
        )

    def observe_decision_outcome(self, *, outcome: str, policy: str) -> None:
        self.traction.observe_decision_outcome(outcome=outcome, policy=policy)

    @contextmanager
    def evaluation_timer(self) -> Iterator[None]:
        with self.traction.evaluation_timer():
            yield

    def observe_audit_write(self, *, write_timestamp: str | None) -> None:
        self.traction.observe_audit_write(write_timestamp=write_timestamp)

    def observe_verification_result(self, *, valid: bool) -> None:
        self.traction.observe_verification_result(valid=valid)

    def observe_active_policies(self, *, count: int) -> None:
        self.traction.observe_active_policies(count=count)

    def exposition(self) -> bytes:
        return generate_latest(self.registry)

    @property
    def content_type(self) -> str:
        return CONTENT_TYPE_LATEST
