from __future__ import annotations

from sena.core.enums import DecisionOutcome, RuleDecision
from sena.core.models import ActionProposal, EvaluationTrace, PolicyRule, RuleEvaluationResult
from sena.policy.interpreter import evaluate_condition


class PolicyEvaluator:
    def __init__(self, rules: list[PolicyRule]):
        self.rules = rules

    def evaluate(self, proposal: ActionProposal, facts: dict) -> EvaluationTrace:
        context = {
            "action_type": proposal.action_type,
            "request_id": proposal.request_id,
            "actor_id": proposal.actor_id,
            **proposal.attributes,
            **facts,
        }
        applicable = [r for r in self.rules if proposal.action_type in r.applies_to]
        evaluated: list[RuleEvaluationResult] = []

        for rule in applicable:
            matched = evaluate_condition(rule.condition, context)
            evaluated.append(
                RuleEvaluationResult(
                    rule_id=rule.id,
                    matched=matched,
                    decision=rule.decision if matched else None,
                    inviolable=rule.inviolable,
                    reason=rule.reason if matched else None,
                )
            )

        matched = [result for result in evaluated if result.matched]
        inviolable_block = any(
            r.inviolable and r.decision == RuleDecision.BLOCK for r in matched
        )
        summary = "No matching policy rules; action approved."
        outcome = DecisionOutcome.APPROVED

        if inviolable_block:
            outcome = DecisionOutcome.BLOCKED
            summary = "Action blocked by inviolable policy rule(s)."
        elif any(r.decision == RuleDecision.BLOCK for r in matched):
            outcome = DecisionOutcome.BLOCKED
            summary = "Action blocked by one or more policy rules."
        elif any(r.decision == RuleDecision.ESCALATE for r in matched):
            outcome = DecisionOutcome.ESCALATE_FOR_HUMAN_REVIEW
            summary = "Action requires human review before execution."

        return EvaluationTrace(
            request_id=proposal.request_id,
            action_type=proposal.action_type,
            outcome=outcome,
            summary=summary,
            applicable_rules=[r.id for r in applicable],
            evaluated_rules=evaluated,
            matched_rules=matched,
            context=context,
        )
