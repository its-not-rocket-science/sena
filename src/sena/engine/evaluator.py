from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from sena import __version__ as SENA_VERSION
from sena.core.enums import DecisionOutcome, RuleDecision
from sena.core.models import (
    ActionProposal,
    AuditRecord,
    DecisionReasoning,
    EvaluatorConfig,
    EvaluationTrace,
    InvariantEvaluationResult,
    PolicyBundleMetadata,
    PolicyInvariant,
    PolicyRule,
    RuleEvaluationResult,
)
from sena.policy.interpreter import evaluate_condition_with_trace
from sena.policy.schema_evolution import evaluate_bundle_compatibility
from sena.policy.validation import (
    SUPPORTED_EVIDENCE_CLASSES,
    validate_ai_originated_action_fields,
    validate_context_schema,
    validate_identity_fields,
)

EVIDENCE_CLASS_TO_FIELDS: dict[str, list[str]] = {
    "source_citations": ["ai_metadata.citation_references"],
    "human_owner": ["ai_metadata.human_owner"],
    "change_ticket": ["change_ticket_id"],
    "simulation_preview": ["simulation_preview_ref"],
    "rollback_plan": ["rollback_plan_ref"],
    "model_provenance": ["ai_metadata.originating_model"],
}


def _missing_evidence_for_class(class_name: str, context: dict[str, object]) -> bool:
    fields = EVIDENCE_CLASS_TO_FIELDS.get(class_name, [class_name])
    for field in fields:
        value = context
        for part in field.split("."):
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return True
        if value is None:
            return True
        if isinstance(value, str) and not value.strip():
            return True
        if isinstance(value, list) and not value:
            return True
    return False


class PolicyEvaluator:
    def __init__(
        self,
        rules: list[PolicyRule],
        invariants: list[PolicyInvariant] | None = None,
        policy_bundle: PolicyBundleMetadata | None = None,
        config: EvaluatorConfig | None = None,
    ):
        self.rules = rules
        self.policy_bundle = policy_bundle or PolicyBundleMetadata(
            bundle_name="default-bundle",
            version="0.1.0-alpha",
            loaded_from="unknown",
        )
        self.invariants = invariants if invariants is not None else list(self.policy_bundle.invariants)
        self.config = config or EvaluatorConfig()
        compatibility = evaluate_bundle_compatibility(schema_version=self.policy_bundle.schema_version, runtime_version=SENA_VERSION)
        if compatibility.errors:
            raise ValueError("policy bundle compatibility check failed: " + "; ".join(compatibility.errors))

    def evaluate(self, proposal: ActionProposal, facts: dict) -> EvaluationTrace:
        decision_id = f"dec_{uuid.uuid4().hex[:12]}"
        context = {
            "action_type": proposal.action_type,
            "request_id": proposal.request_id,
            "actor_id": proposal.actor_id,
            "actor_role": proposal.actor_role,
            "action_origin": proposal.action_origin.value,
            **proposal.attributes,
            **facts,
        }
        if proposal.ai_metadata is not None:
            context["ai_metadata"] = asdict(proposal.ai_metadata)
        if proposal.autonomous_metadata is not None:
            context["autonomous_metadata"] = asdict(proposal.autonomous_metadata)
        applicable = [r for r in self.rules if proposal.action_type in r.applies_to]
        applicable_invariants = [
            invariant for invariant in self.invariants if proposal.action_type in invariant.applies_to
        ]
        evaluated: list[RuleEvaluationResult] = []
        evaluated_invariants: list[InvariantEvaluationResult] = []
        missing_fields: set[str] = set()
        schema_errors: list[str] = []
        identity_errors: list[str] = []
        ai_metadata_errors: list[str] = validate_ai_originated_action_fields(proposal)
        if self.config.require_allow_match:
            identity_errors = validate_identity_fields(proposal.actor_id, proposal.actor_role)
        if self.config.enforce_context_schema and self.policy_bundle.context_schema:
            schema_errors = validate_context_schema(context, self.policy_bundle.context_schema)

        if not schema_errors and not identity_errors and not ai_metadata_errors:
            for invariant in applicable_invariants:
                condition_result = evaluate_condition_with_trace(invariant.condition, context)
                matched = condition_result.matched
                missing_fields.update(condition_result.missing_fields)
                evaluated_invariants.append(
                    InvariantEvaluationResult(
                        invariant_id=invariant.id,
                        matched=matched,
                        reason=invariant.reason if matched else None,
                    )
                )
            for rule in applicable:
                condition_result = evaluate_condition_with_trace(rule.condition, context)
                matched = condition_result.matched
                missing_fields.update(condition_result.missing_fields)
                rule_decision = rule.decision if matched else None
                rule_reason = rule.reason if matched else None
                missing_evidence: list[str] = []
                if (
                    matched
                    and proposal.action_origin.value == "ai_suggested"
                    and rule.required_evidence
                ):
                    missing_evidence = [
                        class_name
                        for class_name in rule.required_evidence
                        if class_name in SUPPORTED_EVIDENCE_CLASSES
                        and _missing_evidence_for_class(class_name, context)
                    ]
                    if missing_evidence:
                        missing_fields.update(
                            f"evidence.{class_name}" for class_name in missing_evidence
                        )
                        rule_decision = rule.missing_evidence_decision or RuleDecision.ESCALATE
                        rule_reason = (
                            f"{rule.reason} Missing governance evidence: "
                            + ", ".join(sorted(missing_evidence))
                            + "."
                        )
                evaluated.append(
                    RuleEvaluationResult(
                        rule_id=rule.id,
                        matched=matched,
                        decision=rule_decision,
                        inviolable=rule.inviolable,
                        reason=rule_reason,
                        required_evidence=list(rule.required_evidence),
                        missing_evidence=missing_evidence,
                    )
                )

        matched = [result for result in evaluated if result.matched]
        matched_invariants = [result for result in evaluated_invariants if result.matched]

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

        if matched_invariants:
            outcome = DecisionOutcome.BLOCKED
            precedence_explanation = (
                "One or more policy invariants were violated. Invariants are fail-closed "
                "safety boundaries and always BLOCK independent of ordinary ALLOW/BLOCK/ESCALATE rules."
            )
            summary = (
                f"Decision {decision_id}: BLOCKED due to invariant violation(s) "
                f"({', '.join(result.invariant_id for result in matched_invariants)})."
            )
        elif inviolable_blocks:
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
        if identity_errors:
            outcome = DecisionOutcome.BLOCKED
            missing_fields.update(identity_errors)
            precedence_explanation = (
                "Strict mode requires actor identity context fields before policy evaluation."
            )
            summary = (
                f"Decision {decision_id}: BLOCKED due to missing identity field(s): "
                f"{', '.join(identity_errors)}"
            )
        if ai_metadata_errors:
            outcome = DecisionOutcome.BLOCKED
            missing_fields.update(ai_metadata_errors)
            precedence_explanation = (
                "AI-originated action proposals require deterministic governance metadata before policy evaluation."
            )
            summary = (
                f"Decision {decision_id}: BLOCKED due to missing AI-governance field(s): "
                f"{', '.join(ai_metadata_errors)}"
            )
        if self.config.require_allow_match and not allows and not matched_invariants:
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

        risk_summary = {
            "risk_attributes": proposal.attributes.get("risk_attributes", {}),
            "requested_action": proposal.attributes.get("requested_action"),
            "workflow_stage": proposal.attributes.get("workflow_stage"),
            "source_system": proposal.attributes.get("source_system"),
            "action_origin": proposal.action_origin.value,
        }
        matched_controls = [
            {
                "rule_id": result.rule_id,
                "decision": result.decision.value if result.decision else None,
                "inviolable": result.inviolable,
                "reason": result.reason,
                "required_evidence": result.required_evidence,
                "missing_evidence": result.missing_evidence,
            }
            for result in matched
        ]
        matched_invariant_controls = [
            {
                "invariant_id": result.invariant_id,
                "reason": result.reason,
            }
            for result in matched_invariants
        ]
        outcome_rationale = [
            f"Outcome resolved to {outcome.value} using deterministic precedence.",
            precedence_explanation,
        ]
        if matched_invariants:
            outcome_rationale.append("Invariant violations are enforced before ordinary rule precedence.")
        if schema_errors:
            outcome_rationale.append("Input context schema validation failed before rule evaluation.")
        if identity_errors:
            outcome_rationale.append("Strict identity checks failed before rule evaluation.")
        if ai_metadata_errors:
            outcome_rationale.append("AI-originated metadata checks failed before rule evaluation.")
        if any(result.missing_evidence for result in matched):
            outcome_rationale.append(
                "Missing governance evidence influenced one or more matched AI-assisted controls."
            )
        reviewer_guidance = [
            "Verify matched controls align with control owner expectations.",
            "Retain decision hash and input fingerprint for audit replay.",
        ]
        if outcome == DecisionOutcome.ESCALATE_FOR_HUMAN_REVIEW:
            reviewer_guidance.append("Manual approval is required before action execution.")
        if outcome == DecisionOutcome.BLOCKED:
            reviewer_guidance.append("Treat as control failure until remediating evidence is attached.")

        decision_timestamp = datetime.now(timezone.utc)
        canonical_payload = {
            "proposal": {
                "action_type": proposal.action_type,
                "request_id": proposal.request_id,
                "actor_id": proposal.actor_id,
                "actor_role": proposal.actor_role,
                "attributes": proposal.attributes,
                "action_origin": proposal.action_origin.value,
                "ai_metadata": asdict(proposal.ai_metadata) if proposal.ai_metadata else None,
                "autonomous_metadata": asdict(proposal.autonomous_metadata) if proposal.autonomous_metadata else None,
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
                    "matched_invariant_ids": sorted(r.invariant_id for r in matched_invariants),
                    "outcome": outcome.value,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        reasoning = DecisionReasoning(
            precedence_explanation=precedence_explanation,
            summary=summary,
            outcome_rationale=outcome_rationale,
            matched_controls=matched_controls,
            matched_invariants=matched_invariant_controls,
            risk_summary=risk_summary,
            reviewer_guidance=reviewer_guidance,
            provenance={
                "bundle_name": self.policy_bundle.bundle_name,
                "bundle_version": self.policy_bundle.version,
                "schema_version": self.policy_bundle.schema_version,
                "evaluator_version": SENA_VERSION,
                "input_fingerprint": input_fingerprint,
                "decision_hash": decision_hash,
            },
        )

        source_metadata = {
            key: value
            for key, value in proposal.attributes.items()
            if key.startswith("source_") or key.startswith("servicenow_") or key.startswith("jira_")
        }
        event_type = str(source_metadata.get("source_event_type") or "decision.evaluated")

        audit_record = AuditRecord(
            decision_id=decision_id,
            timestamp=decision_timestamp,
            write_timestamp=None,
            event_type=event_type,
            action_type=proposal.action_type,
            request_id=proposal.request_id,
            actor_id=proposal.actor_id,
            actor_role=proposal.actor_role,
            outcome=outcome,
            policy_bundle=self.policy_bundle,
            matched_rule_ids=[r.rule_id for r in matched],
            evaluated_rule_ids=[r.rule_id for r in evaluated],
            missing_fields=sorted(missing_fields),
            precedence_explanation=precedence_explanation,
            input_fingerprint=input_fingerprint,
            decision_hash=decision_hash,
            source_metadata=source_metadata,
            request_correlation_id=proposal.request_id,
            evaluator_version=SENA_VERSION,
            policy_bundle_release_id=self.policy_bundle.version,
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
            evaluated_invariants=evaluated_invariants,
            matched_invariants=matched_invariants,
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
