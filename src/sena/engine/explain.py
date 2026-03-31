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
        f"Missing Fields: {', '.join(trace.missing_fields) if trace.missing_fields else 'none'}",
        f"Conflicting Rules: {', '.join(trace.conflicting_rules) if trace.conflicting_rules else 'none'}",
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
