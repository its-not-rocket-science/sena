from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sena.core.models import EvaluationTrace, RuleEvaluationResult

REVIEW_PACKAGE_SCHEMA_VERSION = "1.0"


def _serialize_rule(result: RuleEvaluationResult) -> dict[str, Any]:
    return {
        "rule_id": result.rule_id,
        "matched": result.matched,
        "decision": result.decision.value if result.decision is not None else None,
        "inviolable": result.inviolable,
        "reason": result.reason,
    }


def _normalize_source_references(trace: EvaluationTrace) -> list[dict[str, Any]]:
    if trace.audit_record is None:
        return []

    source_system = str(trace.audit_record.source_metadata.get("source_system") or "unknown")
    references: list[dict[str, Any]] = []

    for key in sorted(trace.audit_record.source_metadata.keys()):
        value = trace.audit_record.source_metadata[key]
        if value is None:
            continue
        if key.startswith("source_") or key.endswith("_id") or key.endswith("_number"):
            references.append(
                {
                    "source_system": source_system,
                    "reference_type": key,
                    "reference_value": str(value),
                }
            )

    if trace.audit_record.request_correlation_id:
        references.append(
            {
                "source_system": source_system,
                "reference_type": "request_correlation_id",
                "reference_value": trace.audit_record.request_correlation_id,
            }
        )

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for ref in references:
        fingerprint = (
            ref["source_system"],
            ref["reference_type"],
            ref["reference_value"],
        )
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(ref)
    return deduped


def build_decision_review_package(trace: EvaluationTrace) -> dict[str, Any]:
    reasoning = trace.reasoning
    package_generated_at = (trace.decision_timestamp or datetime.now(timezone.utc)).isoformat()
    applicable_rule_set = set(trace.applicable_rules)

    return {
        "package_schema_version": REVIEW_PACKAGE_SCHEMA_VERSION,
        "package_type": "sena.decision_review_package",
        "package_generated_at": package_generated_at,
        "decision_summary": {
            "decision_id": trace.decision_id,
            "decision": (trace.decision or trace.outcome).value,
            "outcome": trace.outcome.value,
            "action_type": trace.action_type,
            "summary": trace.summary,
            "decision_timestamp": trace.decision_timestamp.isoformat() if trace.decision_timestamp else None,
        },
        "rules": {
            "matched": [_serialize_rule(rule) for rule in trace.matched_rules],
            "applicable": [
                _serialize_rule(rule)
                for rule in trace.evaluated_rules
                if rule.rule_id in applicable_rule_set
            ],
            "evaluated": [_serialize_rule(rule) for rule in trace.evaluated_rules],
            "conflicting_rule_ids": list(trace.conflicting_rules),
        },
        "precedence": {
            "explanation": reasoning.precedence_explanation if reasoning else None,
            "outcome_rationale": reasoning.outcome_rationale if reasoning else [],
            "reviewer_guidance": reasoning.reviewer_guidance if reasoning else [],
        },
        "facts_and_actor": {
            "actor": {
                "actor_id": trace.audit_record.actor_id if trace.audit_record else None,
                "actor_role": trace.audit_record.actor_role if trace.audit_record else None,
            },
            "facts": trace.context,
            "missing_fields": list(trace.missing_fields),
        },
        "policy_bundle_metadata": {
            "bundle_name": trace.policy_bundle.bundle_name if trace.policy_bundle else None,
            "version": trace.policy_bundle.version if trace.policy_bundle else None,
            "lifecycle": trace.policy_bundle.lifecycle if trace.policy_bundle else None,
            "schema_version": trace.policy_bundle.schema_version if trace.policy_bundle else None,
            "integrity_sha256": trace.policy_bundle.integrity_sha256 if trace.policy_bundle else None,
            "loaded_from": trace.policy_bundle.loaded_from if trace.policy_bundle else None,
        },
        "audit_identifiers": {
            "request_id": trace.request_id,
            "decision_hash": trace.decision_hash,
            "input_fingerprint": trace.audit_record.input_fingerprint if trace.audit_record else None,
            "chain_hash": trace.audit_record.chain_hash if trace.audit_record else None,
            "previous_chain_hash": trace.audit_record.previous_chain_hash if trace.audit_record else None,
            "storage_sequence_number": trace.audit_record.storage_sequence_number if trace.audit_record else None,
        },
        "normalized_source_system_references": _normalize_source_references(trace),
    }
