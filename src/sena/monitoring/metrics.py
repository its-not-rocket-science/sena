from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

sena_decisions_total = Counter(
    "sena_decisions_total",
    "Total decisions by outcome and policy bundle",
    ["outcome", "policy"],
)

sena_evaluation_seconds = Histogram(
    "sena_evaluation_seconds",
    "Policy evaluation duration in seconds",
    buckets=[0.01, 0.05, 0.1, 0.5, 1],
)

sena_audit_entries = Counter(
    "sena_audit_entries_total",
    "Total audit entries written",
)

sena_active_policies = Gauge(
    "sena_active_policies",
    "Number of active policy rules currently loaded",
)

sena_verification_failures = Counter(
    "sena_verification_failures",
    "Total audit verification failures",
)
