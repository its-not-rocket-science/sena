from __future__ import annotations

import uuid

from sena.core.enums import DecisionOutcome, RuleDecision
from sena.core.models import (
    ActionProposal,
    AuditRecord,
    DecisionReasoning,
    EvaluationTrace,
    PolicyBundleMetadata,
    PolicyRule,
    RuleEvaluationResult,
)
from sena.policy.interpreter import evaluate_condition


class PolicyEvaluator:
    def __init__(
        self,
        rules: list[PolicyRule],
        policy_bundle: PolicyBundleMetadata | None = None,
    ):
        self.rules = rules
        self.policy_bundle = policy_bundle or PolicyBundleMetadata(
            bundle_name="default-bundle",
            version="0.1.0-alpha",
            loaded_from="unknown",
        )

    def evaluate(self, proposal: ActionProposal, facts: dict) -> EvaluationTrace:
        decision_id = f"dec_{uuid.uuid4().hex[:12]}"
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

        inviolable_blocks = [
            r for r in matched if r.inviolable and r.decision == RuleDecision.BLOCK
        ]
        blocks = [r for r in matched if r.decision == RuleDecision.BLOCK]
        escalations = [r for r in matched if r.decision == RuleDecision.ESCALATE]

        outcome = DecisionOutcome.APPROVED
        precedence_explanation = "No rules matched, so the action is approved by default."
        summary = (
            f"Decision {decision_id}: APPROVED. No matching policy rules for "
            f"action '{proposal.action_type}'."
        )

        if inviolable_blocks:
            outcome = DecisionOutcome.BLOCKED
            precedence_explanation = (
                "One or more inviolable BLOCK rules matched. Inviolable BLOCK has highest "
                "precedence and overrides all other matches."
            )
            summary = (
                f"Decision {decision_id}: BLOCKED due to inviolable policy constraints "
                f"({', '.join(r.rule_id for r in inviolable_blocks)})."
            )
        elif blocks:
            outcome = DecisionOutcome.BLOCKED
            precedence_explanation = (
                "No inviolable BLOCK matched, but one or more ordinary BLOCK rules matched. "
                "BLOCK takes precedence over ESCALATE and ALLOW."
            )
            summary = (
                f"Decision {decision_id}: BLOCKED by policy rule(s) "
                f"({', '.join(r.rule_id for r in blocks)})."
            )
        elif escalations:
            outcome = DecisionOutcome.ESCALATE_FOR_HUMAN_REVIEW
            precedence_explanation = (
                "No BLOCK rules matched. One or more ESCALATE rules matched, "
                "so manual review is required before execution."
            )
            summary = (
                f"Decision {decision_id}: ESCALATE_FOR_HUMAN_REVIEW for "
                f"rule(s) ({', '.join(r.rule_id for r in escalations)})."
            )

        reasoning = DecisionReasoning(
            precedence_explanation=precedence_explanation,
            summary=summary,
        )
        audit_record = AuditRecord(
            decision_id=decision_id,
            action_type=proposal.action_type,
            request_id=proposal.request_id,
            actor_id=proposal.actor_id,
            outcome=outcome,
            policy_bundle=self.policy_bundle,
            matched_rule_ids=[r.rule_id for r in matched],
            evaluated_rule_ids=[r.rule_id for r in evaluated],
            precedence_explanation=precedence_explanation,
        )

        return EvaluationTrace(
            decision_id=decision_id,
            request_id=proposal.request_id,
            action_type=proposal.action_type,
            decision=outcome,
            outcome=outcome,
            summary=summary,
            policy_bundle=self.policy_bundle,
            reasoning=reasoning,
            applicable_rules=[r.id for r in applicable],
            evaluated_rules=evaluated,
            matched_rules=matched,
            context=context,
            audit_record=audit_record,
        )
