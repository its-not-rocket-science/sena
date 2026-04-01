from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from time import perf_counter
from typing import Iterator

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest


@dataclass(frozen=True)
class _RequestMetricLabels:
    method: str
    path: str
    status_code: str


class ApiMetrics:
    """Application-scoped Prometheus metrics for API monitoring."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry(auto_describe=True)
        self.request_count = Counter(
            "request_count",
            "Total API requests processed",
            labelnames=("method", "path", "status_code"),
            registry=self.registry,
        )
        self.decision_outcome_count = Counter(
            "decision_outcome_count",
            "Total policy decision outcomes",
            labelnames=("endpoint", "outcome"),
            registry=self.registry,
        )
        self.evaluation_latency = Histogram(
            "evaluation_latency",
            "Policy evaluation latency in seconds",
            labelnames=("endpoint",),
            registry=self.registry,
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
        )

    def observe_request(self, *, method: str, path: str, status_code: int) -> None:
        labels = _RequestMetricLabels(method=method, path=path, status_code=str(status_code))
        self.request_count.labels(
            method=labels.method,
            path=labels.path,
            status_code=labels.status_code,
        ).inc()

    def observe_decision_outcome(self, *, endpoint: str, outcome: str) -> None:
        self.decision_outcome_count.labels(endpoint=endpoint, outcome=outcome).inc()

    @contextmanager
    def evaluation_timer(self, *, endpoint: str) -> Iterator[None]:
        start = perf_counter()
        try:
            yield
        finally:
            self.evaluation_latency.labels(endpoint=endpoint).observe(perf_counter() - start)

    def exposition(self) -> bytes:
        return generate_latest(self.registry)

    @property
    def content_type(self) -> str:
        return CONTENT_TYPE_LATEST
