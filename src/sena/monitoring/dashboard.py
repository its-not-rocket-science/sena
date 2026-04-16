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
        self._connector_inbound_events_received: dict[tuple[str, str], int] = {}
        self._connector_outcomes: dict[tuple[str, str, str], int] = {}
        self._exception_overlays_applied: dict[tuple[str, str, str], int] = {}
        self._job_submissions: dict[str, int] = {}
        self._job_terminal_statuses: dict[tuple[str, str], int] = {}
        self.request_count = Counter(
            "request_count",
            "Total API requests processed",
            labelnames=("method", "path", "status_code"),
            registry=registry,
        )
        self.request_duration_seconds = Histogram(
            "request_duration_seconds",
            "HTTP request latency in seconds",
            labelnames=("method", "path"),
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
            registry=registry,
        )
        self.api_errors_total = Counter(
            "api_errors_total",
            "Total API errors by path/code/status",
            labelnames=("path", "error_code", "status_code"),
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
        self.sena_audit_verification_passed = Gauge(
            "sena_audit_verification_passed",
            "Daily full audit verification status (1=passed,0=failed)",
            registry=registry,
        )
        self.sena_connector_inbound_duplicate_suppression_total = Counter(
            "sena_connector_inbound_duplicate_suppression_total",
            "Inbound duplicate webhook deliveries suppressed by connector",
            labelnames=("connector",),
            registry=registry,
        )
        self.sena_connector_inbound_events_received_total = Counter(
            "sena_connector_inbound_events_received_total",
            "Inbound events received by connector and source event type",
            labelnames=("connector", "event_type"),
            registry=registry,
        )
        self.sena_connector_decision_outcomes_total = Counter(
            "sena_connector_decision_outcomes_total",
            "Connector decision outcomes by connector, policy bundle, and outcome",
            labelnames=("connector", "policy_bundle", "outcome"),
            registry=registry,
        )
        self.sena_exception_overlays_applied_total = Counter(
            "sena_exception_overlays_applied_total",
            "Exception overlays applied by connector, policy bundle, and resulting outcome",
            labelnames=("connector", "policy_bundle", "outcome"),
            registry=registry,
        )
        self.sena_connector_outbound_duplicate_suppression_total = Counter(
            "sena_connector_outbound_duplicate_suppression_total",
            "Outbound duplicate deliveries suppressed by connector and target",
            labelnames=("connector", "target"),
            registry=registry,
        )
        self.sena_connector_outbound_dead_letter_total = Counter(
            "sena_connector_outbound_dead_letter_total",
            "Outbound deliveries moved to dead-letter by connector and target",
            labelnames=("connector", "target"),
            registry=registry,
        )
        self.sena_connector_outbound_replay_total = Counter(
            "sena_connector_outbound_replay_total",
            "Outbound dead-letter replay attempts by connector, target, and status",
            labelnames=("connector", "target", "status"),
            registry=registry,
        )
        self.sena_connector_outbound_manual_redrive_total = Counter(
            "sena_connector_outbound_manual_redrive_total",
            "Outbound dead-letter records manually redriven by connector and target",
            labelnames=("connector", "target"),
            registry=registry,
        )
        self.sena_connector_outbound_completion_total = Counter(
            "sena_connector_outbound_completion_total",
            "Outbound completion records created by connector and target",
            labelnames=("connector", "target"),
            registry=registry,
        )
        self.sena_connector_outbound_dead_letter_volume = Gauge(
            "sena_connector_outbound_dead_letter_volume",
            "Current outbound dead-letter queue volume by connector",
            labelnames=("connector",),
            registry=registry,
        )
        self.sena_jobs_submitted_total = Counter(
            "sena_jobs_submitted_total",
            "Asynchronous jobs submitted by job type",
            labelnames=("job_type",),
            registry=registry,
        )
        self.sena_jobs_terminal_total = Counter(
            "sena_jobs_terminal_total",
            "Asynchronous jobs reaching terminal status by job type and status",
            labelnames=("job_type", "status"),
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

    def observe_request_latency(
        self, *, method: str, path: str, duration_seconds: float
    ) -> None:
        self.request_duration_seconds.labels(method=method, path=path).observe(
            max(0.0, duration_seconds)
        )

    def observe_api_error(self, *, path: str, error_code: str, status_code: int) -> None:
        self.api_errors_total.labels(
            path=path, error_code=error_code, status_code=str(status_code)
        ).inc()

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

    def observe_audit_verification_passed(self, *, passed: bool) -> None:
        self.sena_audit_verification_passed.set(1 if passed else 0)

    def observe_active_policies(self, *, count: int) -> None:
        self.sena_active_policies.set(max(0, count))

    def observe_connector_inbound_duplicate_suppression(self, *, connector: str) -> None:
        self.sena_connector_inbound_duplicate_suppression_total.labels(
            connector=connector
        ).inc()

    def observe_connector_inbound_event_received(
        self, *, connector: str, event_type: str
    ) -> None:
        normalized_event_type = event_type or "unknown"
        self.sena_connector_inbound_events_received_total.labels(
            connector=connector,
            event_type=normalized_event_type,
        ).inc()
        key = (connector, normalized_event_type)
        self._connector_inbound_events_received[key] = (
            self._connector_inbound_events_received.get(key, 0) + 1
        )

    def observe_connector_outcome(
        self, *, connector: str, policy_bundle: str, outcome: str
    ) -> None:
        self.sena_connector_decision_outcomes_total.labels(
            connector=connector,
            policy_bundle=policy_bundle,
            outcome=outcome,
        ).inc()
        key = (connector, policy_bundle, outcome)
        self._connector_outcomes[key] = self._connector_outcomes.get(key, 0) + 1

    def observe_exception_overlay_applied(
        self, *, connector: str, policy_bundle: str, outcome: str
    ) -> None:
        self.sena_exception_overlays_applied_total.labels(
            connector=connector,
            policy_bundle=policy_bundle,
            outcome=outcome,
        ).inc()
        key = (connector, policy_bundle, outcome)
        self._exception_overlays_applied[key] = (
            self._exception_overlays_applied.get(key, 0) + 1
        )

    def observe_connector_outbound_duplicate_suppression(
        self, *, connector: str, target: str
    ) -> None:
        self.sena_connector_outbound_duplicate_suppression_total.labels(
            connector=connector, target=target
        ).inc()

    def observe_connector_outbound_dead_letter(
        self, *, connector: str, target: str
    ) -> None:
        self.sena_connector_outbound_dead_letter_total.labels(
            connector=connector, target=target
        ).inc()
        dead_letter = self.sena_connector_outbound_dead_letter_volume.labels(
            connector=connector
        )
        dead_letter.inc()

    def observe_connector_outbound_dead_letter_removed(self, *, connector: str) -> None:
        dead_letter = self.sena_connector_outbound_dead_letter_volume.labels(
            connector=connector
        )
        dead_letter.dec()

    def observe_connector_outbound_replay(
        self, *, connector: str, target: str, status: str
    ) -> None:
        self.sena_connector_outbound_replay_total.labels(
            connector=connector, target=target, status=status
        ).inc()

    def observe_connector_outbound_manual_redrive(
        self, *, connector: str, target: str
    ) -> None:
        self.sena_connector_outbound_manual_redrive_total.labels(
            connector=connector, target=target
        ).inc()

    def observe_connector_outbound_completion(self, *, connector: str, target: str) -> None:
        self.sena_connector_outbound_completion_total.labels(
            connector=connector, target=target
        ).inc()

    def observe_job_submitted(self, *, job_type: str) -> None:
        self.sena_jobs_submitted_total.labels(job_type=job_type).inc()
        self._job_submissions[job_type] = self._job_submissions.get(job_type, 0) + 1

    def observe_job_terminal(self, *, job_type: str, status: str) -> None:
        self.sena_jobs_terminal_total.labels(job_type=job_type, status=status).inc()
        key = (job_type, status)
        self._job_terminal_statuses[key] = self._job_terminal_statuses.get(key, 0) + 1

    def observability_snapshot(self) -> dict[str, object]:
        return {
            "inbound_events_received": [
                {"connector": c, "event_type": e, "count": count}
                for (c, e), count in sorted(self._connector_inbound_events_received.items())
            ],
            "outcomes_by_connector_policy_bundle": [
                {
                    "connector": c,
                    "policy_bundle": p,
                    "outcome": o,
                    "count": count,
                }
                for (c, p, o), count in sorted(self._connector_outcomes.items())
            ],
            "exception_overlays_applied": [
                {
                    "connector": c,
                    "policy_bundle": p,
                    "outcome": o,
                    "count": count,
                }
                for (c, p, o), count in sorted(self._exception_overlays_applied.items())
            ],
            "jobs": {
                "submitted": [
                    {"job_type": job_type, "count": count}
                    for job_type, count in sorted(self._job_submissions.items())
                ],
                "terminal": [
                    {"job_type": job_type, "status": status, "count": count}
                    for (job_type, status), count in sorted(
                        self._job_terminal_statuses.items()
                    )
                ],
            },
        }


def _parse_iso_timestamp_to_epoch(value: str | None) -> float | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()
