from sena.core.models import EvaluationTrace


def format_trace(trace: EvaluationTrace) -> str:
    lines = [
        f"Action: {trace.action_type}",
        f"Outcome: {trace.outcome.value}",
        f"Summary: {trace.summary}",
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
