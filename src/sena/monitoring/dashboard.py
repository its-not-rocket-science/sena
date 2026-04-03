from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Iterator

from prometheus_client import Counter, Gauge, Histogram


@dataclass(frozen=True)
class _RequestMetricLabels:
    method: str
    path: str
    status_code: str


class TractionMetrics:
    """Prometheus metrics used for API observability."""

    def __init__(self, *, registry) -> None:
        self.request_count = Counter(
            "request_count",
            "Total API requests processed",
            labelnames=("method", "path", "status_code"),
            registry=registry,
        )
        self.sena_decisions_total = Counter(
            "sena_decisions_total",
            "Total decisions",
            labelnames=("outcome", "policy"),
            registry=registry,
        )
        self.sena_evaluation_seconds = Histogram(
            "sena_evaluation_seconds",
            "Evaluation latency",
            registry=registry,
            buckets=(0.01, 0.05, 0.1, 0.5, 1),
        )
        self.sena_audit_entries_total = Counter(
            "sena_audit_entries_total",
            "Audit entries written",
            registry=registry,
        )
        self.sena_active_policies = Gauge(
            "sena_active_policies",
            "Number of active policy rules loaded",
            registry=registry,
        )
        self.sena_merkle_root_timestamp = Gauge(
            "sena_merkle_root_timestamp",
            "Last Merkle root timestamp",
            registry=registry,
        )
        self.sena_verification_requests = Counter(
            "sena_verification_requests",
            "Proof verification requests",
            registry=registry,
        )
        self.sena_verification_failures = Counter(
            "sena_verification_failures",
            "Failed verifications",
            registry=registry,
        )

    def observe_request(self, *, method: str, path: str, status_code: int) -> None:
        labels = _RequestMetricLabels(
            method=method, path=path, status_code=str(status_code)
        )
        self.request_count.labels(
            method=labels.method,
            path=labels.path,
            status_code=labels.status_code,
        ).inc()

    def observe_decision_outcome(self, *, outcome: str, policy: str) -> None:
        self.sena_decisions_total.labels(outcome=outcome, policy=policy).inc()

    @contextmanager
    def evaluation_timer(self) -> Iterator[None]:
        start = perf_counter()
        try:
            yield
        finally:
            self.sena_evaluation_seconds.observe(perf_counter() - start)

    def observe_audit_write(self, *, write_timestamp: str | None) -> None:
        self.sena_audit_entries_total.inc()
        timestamp_epoch = _parse_iso_timestamp_to_epoch(write_timestamp)
        if timestamp_epoch is not None:
            self.sena_merkle_root_timestamp.set(timestamp_epoch)

    def observe_verification_result(self, *, valid: bool) -> None:
        self.sena_verification_requests.inc()
        if not valid:
            self.sena_verification_failures.inc()

    def observe_active_policies(self, *, count: int) -> None:
        self.sena_active_policies.set(max(0, count))


def _parse_iso_timestamp_to_epoch(value: str | None) -> float | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()
