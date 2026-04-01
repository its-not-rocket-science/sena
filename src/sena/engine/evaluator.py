from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from sena.core.enums import DecisionOutcome, RuleDecision
from sena.core.models import (
    ActionProposal,
    AuditRecord,
    DecisionReasoning,
    EvaluatorConfig,
    EvaluationTrace,
    PolicyBundleMetadata,
    PolicyRule,
    RuleEvaluationResult,
)
from sena.policy.interpreter import evaluate_condition_with_trace
from sena.policy.validation import validate_context_schema


class PolicyEvaluator:
    def __init__(
        self,
        rules: list[PolicyRule],
        policy_bundle: PolicyBundleMetadata | None = None,
        config: EvaluatorConfig | None = None,
    ):
        self.rules = rules
        self.policy_bundle = policy_bundle or PolicyBundleMetadata(
            bundle_name="default-bundle",
            version="0.1.0-alpha",
            loaded_from="unknown",
        )
        self.config = config or EvaluatorConfig()

    def evaluate(self, proposal: ActionProposal, facts: dict) -> EvaluationTrace:
        decision_id = f"dec_{uuid.uuid4().hex[:12]}"
        context = {
            "action_type": proposal.action_type,
            "request_id": proposal.request_id,
            "actor_id": proposal.actor_id,
            "actor_role": proposal.actor_role,
            "actor": {
                "id": proposal.actor_id,
                "role": proposal.actor_role,
            },
            **proposal.attributes,
            **facts,
        }
        applicable = [r for r in self.rules if proposal.action_type in r.applies_to]
        evaluated: list[RuleEvaluationResult] = []
        missing_fields: set[str] = set()
        schema_errors: list[str] = []
        if self.config.enforce_context_schema and self.policy_bundle.context_schema:
            schema_errors = validate_context_schema(context, self.policy_bundle.context_schema)

        if not schema_errors:
            for rule in applicable:
                condition_result = evaluate_condition_with_trace(rule.condition, context)
                matched = condition_result.matched
                missing_fields.update(condition_result.missing_fields)
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
        allows = [r for r in matched if r.decision == RuleDecision.ALLOW]
        conflicting_rules = sorted({r.rule_id for r in matched if r.decision != matched[0].decision}) if matched else []

        outcome = self.config.default_decision
        precedence_explanation = (
            f"No rules matched. Fallback decision is {self.config.default_decision.value} "
            "per evaluator configuration."
        )
        summary = f"Decision {decision_id}: {outcome.value}. No matching policy rules for action '{proposal.action_type}'."

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
        if schema_errors:
            outcome = DecisionOutcome.BLOCKED
            precedence_explanation = (
                "Context schema validation failed before policy evaluation; blocked deterministically."
            )
            summary = (
                f"Decision {decision_id}: BLOCKED due to context schema errors: "
                f"{'; '.join(schema_errors)}"
            )
        if self.config.require_allow_match and not allows:
            outcome = DecisionOutcome.BLOCKED
            if not matched:
                precedence_explanation = (
                    "Strict allow mode is enabled and no rules matched. "
                    "At least one ALLOW rule must match."
                )
                summary = (
                    f"Decision {decision_id}: BLOCKED because no matching policy rules were "
                    "found under strict allow mode."
                )
            else:
                precedence_explanation = (
                    "Strict allow mode is enabled. Matching rules were found, but none were ALLOW."
                )
                summary = (
                    f"Decision {decision_id}: BLOCKED because strict allow mode requires at "
                    "least one matching ALLOW rule."
                )

        if not matched and self.config.default_decision != DecisionOutcome.APPROVED:
            summary = (
                f"Decision {decision_id}: {outcome.value} because no matching policy rules "
                f"were found under {self.config.default_decision.value.lower()}-by-default mode."
            )

        if conflicting_rules:
            precedence_explanation = (
                f"{precedence_explanation} Multiple conflicting rules matched; "
                "BLOCK takes precedence over ESCALATE and ALLOW."
            )

        reasoning = DecisionReasoning(
            precedence_explanation=precedence_explanation,
            summary=summary,
        )
        decision_timestamp = datetime.now(timezone.utc)
        canonical_payload = {
            "proposal": {
                "action_type": proposal.action_type,
                "request_id": proposal.request_id,
                "actor_id": proposal.actor_id,
                "actor_role": proposal.actor_role,
                "attributes": proposal.attributes,
            },
            "facts": facts,
        }
        input_fingerprint = hashlib.sha256(
            json.dumps(canonical_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        decision_hash = hashlib.sha256(
            json.dumps(
                {
                    "input_fingerprint": input_fingerprint,
                    "policy_bundle": {
                        "bundle_name": self.policy_bundle.bundle_name,
                        "version": self.policy_bundle.version,
                    },
                    "matched_rule_ids": sorted(r.rule_id for r in matched),
                    "outcome": outcome.value,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        audit_record = AuditRecord(
            decision_id=decision_id,
            timestamp=decision_timestamp,
            action_type=proposal.action_type,
            request_id=proposal.request_id,
            actor_id=proposal.actor_id,
            outcome=outcome,
            policy_bundle=self.policy_bundle,
            matched_rule_ids=[r.rule_id for r in matched],
            evaluated_rule_ids=[r.rule_id for r in evaluated],
            missing_fields=sorted(missing_fields),
            precedence_explanation=precedence_explanation,
            input_fingerprint=input_fingerprint,
            decision_hash=decision_hash,
        )

        trace = EvaluationTrace(
            decision_id=decision_id,
            decision_timestamp=decision_timestamp,
            decision_hash=decision_hash,
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
            conflicting_rules=conflicting_rules,
            missing_fields=sorted(missing_fields),
            context=context,
            audit_record=audit_record,
        )
        if (
            trace.outcome == DecisionOutcome.ESCALATE_FOR_HUMAN_REVIEW
            and self.config.on_escalation is not None
        ):
            self.config.on_escalation(trace)
        return trace
