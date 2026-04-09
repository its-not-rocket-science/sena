from sena.core.models import EvaluationTrace


def format_trace(trace: EvaluationTrace) -> str:
    lines = [
        f"Decision ID: {trace.decision_id}",
        f"Action: {trace.action_type}",
        f"Outcome: {trace.outcome.value}",
        f"Summary: {trace.summary}",
        f"Decision Timestamp: {trace.decision_timestamp.isoformat() if trace.decision_timestamp else 'n/a'}",
        f"Decision Hash: {trace.decision_hash or 'n/a'}",
        f"Precedence: {trace.reasoning.precedence_explanation if trace.reasoning else 'n/a'}",
        f"Outcome Rationale: {' | '.join(trace.reasoning.outcome_rationale) if trace.reasoning else 'n/a'}",
        f"Reviewer Guidance: {' | '.join(trace.reasoning.reviewer_guidance) if trace.reasoning else 'n/a'}",
        f"Missing Fields: {', '.join(trace.missing_fields) if trace.missing_fields else 'none'}",
        f"Conflicting Rules: {', '.join(trace.conflicting_rules) if trace.conflicting_rules else 'none'}",
        f"Risk Summary: {trace.reasoning.risk_summary if trace.reasoning else {}}",
        f"Provenance: {trace.reasoning.provenance if trace.reasoning else {}}",
        "Rule Evaluations:",
    ]

    if not trace.evaluated_rules:
        lines.append("  - none")
        return "\n".join(lines)

    for rule in trace.evaluated_rules:
        status = "MATCH" if rule.matched else "NO_MATCH"
        lines.append(
            f"  - {rule.rule_id} status={status} decision={rule.decision} "
            f"inviolable={rule.inviolable} reason={rule.reason}"
        )
    return "\n".join(lines)


def build_explanation(trace: EvaluationTrace, *, view: str = "auditor") -> dict:
    if view not in {"analyst", "auditor"}:
        raise ValueError("view must be one of: analyst, auditor")

    matched_rule_ids = [result.rule_id for result in trace.matched_rules]
    base = {
        "decision_id": trace.decision_id,
        "action_type": trace.action_type,
        "outcome": trace.outcome.value,
        "summary": trace.summary,
        "view": view,
    }
    if view == "analyst":
        base["analyst_summary"] = {
            "matched_rule_ids": matched_rule_ids,
            "matched_rule_count": len(matched_rule_ids),
            "missing_fields": trace.missing_fields,
            "precedence": trace.reasoning.precedence_explanation if trace.reasoning else None,
        }
        return base

    base["auditor_trace"] = {
        "decision_timestamp": trace.decision_timestamp.isoformat() if trace.decision_timestamp else None,
        "decision_hash": trace.decision_hash,
        "policy_bundle": {
            "bundle_name": trace.policy_bundle.bundle_name,
            "version": trace.policy_bundle.version,
            "schema_version": trace.policy_bundle.schema_version,
        }
        if trace.policy_bundle
        else None,
        "rules": {
            "applicable_rule_ids": trace.applicable_rules,
            "evaluated": [
                {
                    "rule_id": result.rule_id,
                    "matched": result.matched,
                    "decision": result.decision.value if result.decision else None,
                    "inviolable": result.inviolable,
                    "reason": result.reason,
                    "condition_evaluation": {
                        "matched": result.condition_matched,
                        "missing_fields": result.condition_missing_fields,
                    },
                    "missing_evidence": result.missing_evidence,
                }
                for result in trace.evaluated_rules
            ],
            "matched_rule_ids": matched_rule_ids,
        },
        "precedence_resolution": [
            {
                "stage": step.stage,
                "description": step.description,
                "matched_rule_ids": step.matched_rule_ids,
                "outcome": step.outcome.value if step.outcome else None,
            }
            for step in trace.precedence_steps
        ],
        "reasoning": trace.reasoning.summary if trace.reasoning else None,
        "reasoning_details": trace.reasoning.outcome_rationale if trace.reasoning else [],
        "invariants": [
            {"invariant_id": item.invariant_id, "matched": item.matched, "reason": item.reason}
            for item in trace.evaluated_invariants
        ],
        "exceptions": {
            "evaluated": [
                {
                    "exception_id": item.exception_id,
                    "matched": item.matched,
                    "expired": item.expired,
                    "changed_outcome": item.changed_outcome,
                    "override_outcome": item.override_outcome.value if item.override_outcome else None,
                    "reason": item.reason,
                }
                for item in trace.evaluated_exceptions
            ],
            "applied_exception_ids": [item.exception_id for item in trace.applied_exceptions],
            "baseline_outcome": trace.baseline_outcome.value if trace.baseline_outcome else None,
        },
        "missing_fields": trace.missing_fields,
    }
    return base
