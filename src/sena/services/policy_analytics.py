from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sena.audit.sinks import JsonlFileAuditSink


@dataclass(frozen=True)
class PolicyEfficacyAnalytics:
    audit_path: str

    def compute(self) -> dict[str, Any]:
        rows = JsonlFileAuditSink(path=self.audit_path).load_records()
        grouped: dict[str, dict[str, Any]] = {}

        for row in rows:
            policy_bundle = _policy_bundle_key(row)
            metrics = grouped.setdefault(
                policy_bundle,
                {
                    "policy_bundle": policy_bundle,
                    "total_decisions": 0,
                    "downstream_recorded": 0,
                    "downstream_success": 0,
                    "downstream_failure": 0,
                    "incident_count": 0,
                    "decision_outcomes": {},
                },
            )
            metrics["total_decisions"] += 1

            outcome = str(row.get("outcome") or "UNKNOWN")
            metrics["decision_outcomes"][outcome] = (
                metrics["decision_outcomes"].get(outcome, 0) + 1
            )

            downstream = str(row.get("downstream_outcome") or "").strip().lower()
            if downstream in {"success", "failure"}:
                metrics["downstream_recorded"] += 1
                if downstream == "success":
                    metrics["downstream_success"] += 1
                else:
                    metrics["downstream_failure"] += 1

            if bool(row.get("incident_flag")):
                metrics["incident_count"] += 1

        bundles = [_finalize(metrics) for metrics in grouped.values()]
        bundles.sort(key=lambda item: item["policy_bundle"])

        totals = {
            "total_decisions": sum(item["total_decisions"] for item in bundles),
            "downstream_recorded": sum(item["downstream_recorded"] for item in bundles),
            "downstream_success": sum(item["downstream_success"] for item in bundles),
            "downstream_failure": sum(item["downstream_failure"] for item in bundles),
            "incident_count": sum(item["incident_count"] for item in bundles),
        }
        totals["success_rate"] = _ratio(
            totals["downstream_success"], totals["downstream_recorded"]
        )
        totals["incident_rate"] = _ratio(
            totals["incident_count"], totals["total_decisions"]
        )
        totals["efficacy_score"] = _round(
            totals["success_rate"] * (1.0 - totals["incident_rate"])
        )

        return {
            "generated_from_records": len(rows),
            "policy_bundles": bundles,
            "totals": totals,
            "dashboard_example": _dashboard_example(bundles),
        }


def _policy_bundle_key(row: dict[str, Any]) -> str:
    policy_bundle = row.get("policy_bundle")
    if isinstance(policy_bundle, dict):
        bundle_name = str(policy_bundle.get("bundle_name") or "unknown")
        version = str(policy_bundle.get("version") or "unknown")
        return f"{bundle_name}:{version}"
    if isinstance(policy_bundle, str) and policy_bundle.strip():
        return policy_bundle.strip()
    return "unknown:unknown"


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return _round(numerator / denominator)


def _round(value: float) -> float:
    return round(value, 4)


def _finalize(metrics: dict[str, Any]) -> dict[str, Any]:
    metrics["success_rate"] = _ratio(
        metrics["downstream_success"], metrics["downstream_recorded"]
    )
    metrics["incident_rate"] = _ratio(
        metrics["incident_count"], metrics["total_decisions"]
    )
    metrics["efficacy_score"] = _round(
        metrics["success_rate"] * (1.0 - metrics["incident_rate"])
    )
    return metrics


def _dashboard_example(bundles: list[dict[str, Any]]) -> dict[str, Any]:
    series = [
        {
            "policy_bundle": item["policy_bundle"],
            "efficacy_score": item["efficacy_score"],
            "success_rate": item["success_rate"],
            "incident_rate": item["incident_rate"],
        }
        for item in bundles
    ]
    return {
        "title": "Policy Efficacy Overview",
        "x_axis": "policy_bundle",
        "series": series,
    }
