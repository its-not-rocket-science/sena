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

    def observe_request_latency(
        self, *, method: str, path: str, duration_seconds: float
    ) -> None:
        self.traction.observe_request_latency(
            method=method, path=path, duration_seconds=duration_seconds
        )

    def observe_api_error(self, *, path: str, error_code: str, status_code: int) -> None:
        self.traction.observe_api_error(
            path=path, error_code=error_code, status_code=status_code
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

    def observe_audit_verification_passed(self, *, passed: bool) -> None:
        self.traction.observe_audit_verification_passed(passed=passed)

    def observe_active_policies(self, *, count: int) -> None:
        self.traction.observe_active_policies(count=count)

    def connector_reliability_observer(self, *, connector: str) -> "ConnectorReliabilityObserver":
        return ConnectorReliabilityObserver(metrics=self, connector=connector)

    def observe_connector_inbound_duplicate_suppression(self, *, connector: str) -> None:
        self.traction.observe_connector_inbound_duplicate_suppression(
            connector=connector
        )

    def observe_connector_outbound_duplicate_suppression(
        self, *, connector: str, target: str
    ) -> None:
        self.traction.observe_connector_outbound_duplicate_suppression(
            connector=connector,
            target=target,
        )

    def observe_connector_outbound_dead_letter(
        self, *, connector: str, target: str
    ) -> None:
        self.traction.observe_connector_outbound_dead_letter(
            connector=connector,
            target=target,
        )

    def observe_connector_outbound_dead_letter_removed(self, *, connector: str) -> None:
        self.traction.observe_connector_outbound_dead_letter_removed(connector=connector)

    def observe_connector_outbound_replay(
        self, *, connector: str, target: str, status: str
    ) -> None:
        self.traction.observe_connector_outbound_replay(
            connector=connector,
            target=target,
            status=status,
        )

    def observe_connector_outbound_manual_redrive(
        self, *, connector: str, target: str
    ) -> None:
        self.traction.observe_connector_outbound_manual_redrive(
            connector=connector,
            target=target,
        )

    def observe_connector_outbound_completion(self, *, connector: str, target: str) -> None:
        self.traction.observe_connector_outbound_completion(
            connector=connector,
            target=target,
        )

    def exposition(self) -> bytes:
        return generate_latest(self.registry)

    @property
    def content_type(self) -> str:
        return CONTENT_TYPE_LATEST


class ConnectorReliabilityObserver:
    def __init__(self, *, metrics: ApiMetrics, connector: str) -> None:
        self._metrics = metrics
        self._connector = connector

    def record_inbound_duplicate_suppression(self) -> None:
        self._metrics.observe_connector_inbound_duplicate_suppression(
            connector=self._connector
        )

    def record_outbound_duplicate_suppression(self, *, target: str) -> None:
        self._metrics.observe_connector_outbound_duplicate_suppression(
            connector=self._connector,
            target=target,
        )

    def record_outbound_dead_letter(self, *, target: str) -> None:
        self._metrics.observe_connector_outbound_dead_letter(
            connector=self._connector,
            target=target,
        )

    def record_outbound_dead_letter_removed(self) -> None:
        self._metrics.observe_connector_outbound_dead_letter_removed(
            connector=self._connector
        )

    def record_outbound_replay(self, *, target: str, status: str) -> None:
        self._metrics.observe_connector_outbound_replay(
            connector=self._connector,
            target=target,
            status=status,
        )

    def record_outbound_manual_redrive(self, *, target: str) -> None:
        self._metrics.observe_connector_outbound_manual_redrive(
            connector=self._connector,
            target=target,
        )

    def record_outbound_completion(self, *, target: str) -> None:
        self._metrics.observe_connector_outbound_completion(
            connector=self._connector,
            target=target,
        )
