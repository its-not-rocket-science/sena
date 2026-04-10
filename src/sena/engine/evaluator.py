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
    ExceptionEvaluationResult,
    ExceptionScope,
    EvaluationTrace,
    InvariantEvaluationResult,
    PolicyException,
    PolicyBundleMetadata,
    PolicyInvariant,
    PolicyRule,
    PrecedenceResolutionStep,
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
        exceptions: list[PolicyException] | None = None,
        policy_bundle: PolicyBundleMetadata | None = None,
        config: EvaluatorConfig | None = None,
    ):
        self.rules = rules
        self.policy_bundle = policy_bundle or PolicyBundleMetadata(
            bundle_name="default-bundle",
            version="0.1.0-alpha",
            loaded_from="unknown",
        )
        self.invariants = (
            invariants
            if invariants is not None
            else list(self.policy_bundle.invariants)
        )
        self.exceptions = list(exceptions or [])
        self.config = config or EvaluatorConfig()
        compatibility = evaluate_bundle_compatibility(
            schema_version=self.policy_bundle.schema_version,
            runtime_version=SENA_VERSION,
        )
        if compatibility.errors:
            raise ValueError(
                "policy bundle compatibility check failed: "
                + "; ".join(compatibility.errors)
            )

    @staticmethod
    def _normalize_timestamp(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _scope_matches(scope: ExceptionScope, proposal: ActionProposal) -> bool:
        if scope.action_type != proposal.action_type:
            return False
        if scope.actor is not None and scope.actor != proposal.actor_id:
            return False
        for key, expected in scope.attributes.items():
            if proposal.attributes.get(key) != expected:
                return False
        return True

    @staticmethod
    def _stable_summary(text: str) -> str:
        return " ".join(text.split())

    def _apply_exception_overlay(
        self,
        *,
        proposal: ActionProposal,
        baseline_outcome: DecisionOutcome,
        decision_time: datetime,
    ) -> tuple[
        DecisionOutcome,
        list[ExceptionEvaluationResult],
        list[ExceptionEvaluationResult],
        str | None,
    ]:
        evaluated: list[ExceptionEvaluationResult] = []
        applied: list[ExceptionEvaluationResult] = []
        overlay_note: str | None = None
        outcome = baseline_outcome
        normalized_time = self._normalize_timestamp(decision_time)
        for item in sorted(self.exceptions, key=lambda exc: exc.exception_id):
            expired = self._normalize_timestamp(item.expiry) <= normalized_time
            matched = (
                not expired
                and item.approved_at is not None
                and self._scope_matches(item.scope, proposal)
            )
            changed = (
                matched
                and baseline_outcome != DecisionOutcome.APPROVED
                and baseline_outcome != DecisionOutcome.BLOCKED
            )
            override = DecisionOutcome.APPROVED if changed else None
            reason = None
            if expired:
                reason = "expired_exception_ignored"
            elif item.approved_at is None:
                reason = "pending_approval"
            elif matched:
                reason = "approved_exception_match"
            evaluated_result = ExceptionEvaluationResult(
                exception_id=item.exception_id,
                matched=matched,
                expired=expired,
                changed_outcome=changed,
                override_outcome=override,
                reason=reason,
            )
            evaluated.append(evaluated_result)
            if matched:
                applied.append(evaluated_result)
        if applied:
            changed_results = [result for result in applied if result.changed_outcome]
            if changed_results:
                changed_ids = ", ".join(result.exception_id for result in changed_results)
                outcome = DecisionOutcome.APPROVED
                overlay_note = (
                    "Exception overlay applied after baseline evaluation. "
                    f"Approved exception(s) changed baseline outcome to APPROVED: {changed_ids}."
                )
            else:
                overlay_note = (
                    "Exception overlay evaluated approved exceptions, but baseline "
                    "outcome remained unchanged due to safety constraints."
                )
        return outcome, evaluated, applied, overlay_note

    @staticmethod
    def _build_context(proposal: ActionProposal, facts: dict) -> dict[str, object]:
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
        return context

    def _run_pre_evaluation_validation(
        self, proposal: ActionProposal, context: dict[str, object]
    ) -> tuple[list[str], list[str], list[str]]:
        schema_errors: list[str] = []
        identity_errors: list[str] = []
        ai_metadata_errors = validate_ai_originated_action_fields(proposal)
        if self.config.require_allow_match:
            identity_errors = validate_identity_fields(
                proposal.actor_id, proposal.actor_role
            )
        if self.config.enforce_context_schema and self.policy_bundle.context_schema:
            schema_errors = validate_context_schema(
                context, self.policy_bundle.context_schema
            )
        return schema_errors, identity_errors, ai_metadata_errors

    @staticmethod
    def _evaluate_invariants(
        applicable_invariants: list[PolicyInvariant],
        context: dict[str, object],
        missing_fields: set[str],
    ) -> list[InvariantEvaluationResult]:
        evaluated_invariants: list[InvariantEvaluationResult] = []
        for invariant in applicable_invariants:
            condition_result = evaluate_condition_with_trace(
                invariant.condition, context
            )
            missing_fields.update(condition_result.missing_fields)
            evaluated_invariants.append(
                InvariantEvaluationResult(
                    invariant_id=invariant.id,
                    matched=condition_result.matched,
                    reason=invariant.reason if condition_result.matched else None,
                )
            )
        return evaluated_invariants

    def _evaluate_rules(
        self,
        *,
        applicable: list[PolicyRule],
        proposal: ActionProposal,
        context: dict[str, object],
        missing_fields: set[str],
    ) -> list[RuleEvaluationResult]:
        evaluated: list[RuleEvaluationResult] = []
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
                    rule_decision = (
                        rule.missing_evidence_decision or RuleDecision.ESCALATE
                    )
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
                    condition_matched=condition_result.matched,
                    condition_missing_fields=sorted(condition_result.missing_fields),
                )
            )
        return evaluated

    @staticmethod
    def _build_skipped_rule_results(
        applicable: list[PolicyRule], skip_reason: str
    ) -> list[RuleEvaluationResult]:
        return [
            RuleEvaluationResult(
                rule_id=rule.id,
                matched=False,
                decision=None,
                inviolable=rule.inviolable,
                reason=skip_reason,
            )
            for rule in applicable
        ]

    def _resolve_precedence(
        self,
        *,
        proposal: ActionProposal,
        evaluated: list[RuleEvaluationResult],
        evaluated_invariants: list[InvariantEvaluationResult],
        schema_errors: list[str],
        identity_errors: list[str],
        ai_metadata_errors: list[str],
        missing_fields: set[str],
        precedence_steps: list[PrecedenceResolutionStep],
    ) -> tuple[
        DecisionOutcome,
        str,
        str,
        list[RuleEvaluationResult],
        list[InvariantEvaluationResult],
        list[str],
    ]:
        matched = [result for result in evaluated if result.matched]
        matched_invariants = [
            result for result in evaluated_invariants if result.matched
        ]

        inviolable_blocks = [
            r for r in matched if r.inviolable and r.decision == RuleDecision.BLOCK
        ]
        blocks = [r for r in matched if r.decision == RuleDecision.BLOCK]
        escalations = [r for r in matched if r.decision == RuleDecision.ESCALATE]
        allows = [r for r in matched if r.decision == RuleDecision.ALLOW]
        decision_classes = {result.decision for result in matched}
        conflict_decision: RuleDecision | None = None
        if len(decision_classes) > 1:
            if RuleDecision.BLOCK in decision_classes:
                conflict_decision = RuleDecision.BLOCK
            elif RuleDecision.ESCALATE in decision_classes:
                conflict_decision = RuleDecision.ESCALATE
            else:
                conflict_decision = RuleDecision.ALLOW
        conflicting_rules = (
            sorted(
                result.rule_id
                for result in matched
                if result.decision == conflict_decision
            )
            if conflict_decision is not None
            else []
        )

        outcome = self.config.default_decision
        precedence_explanation = (
            f"No rules matched. Fallback decision is {self.config.default_decision.value} "
            "per evaluator configuration."
        )
        summary = (
            f"{outcome.value}. No matching policy rules for action "
            f"'{proposal.action_type}'."
        )
        if matched_invariants:
            outcome = DecisionOutcome.BLOCKED
            precedence_explanation = (
                "One or more policy invariants were violated. Invariants are fail-closed "
                "safety boundaries and always BLOCK independent of ordinary ALLOW/BLOCK/ESCALATE rules."
            )
            summary = (
                "BLOCKED due to invariant violation(s) "
                f"({', '.join(result.invariant_id for result in matched_invariants)})."
            )
            precedence_steps.append(
                PrecedenceResolutionStep(
                    stage="invariant_precedence",
                    description="Invariant violations force a BLOCKED outcome.",
                    matched_rule_ids=sorted(
                        result.invariant_id for result in matched_invariants
                    ),
                    outcome=outcome,
                )
            )
        elif inviolable_blocks:
            outcome = DecisionOutcome.BLOCKED
            precedence_explanation = (
                "One or more inviolable BLOCK rules matched. Inviolable BLOCK has highest "
                "precedence and overrides all other matches."
            )
            summary = (
                "BLOCKED due to inviolable policy constraints "
                f"({', '.join(r.rule_id for r in inviolable_blocks)})."
            )
            precedence_steps.append(
                PrecedenceResolutionStep(
                    stage="inviolable_block_precedence",
                    description="Matched inviolable BLOCK rules override all other rule decisions.",
                    matched_rule_ids=sorted(r.rule_id for r in inviolable_blocks),
                    outcome=outcome,
                )
            )
        elif blocks:
            outcome = DecisionOutcome.BLOCKED
            precedence_explanation = (
                "No inviolable BLOCK matched, but one or more ordinary BLOCK rules matched. "
                "BLOCK takes precedence over ESCALATE and ALLOW."
            )
            summary = (
                "BLOCKED by policy rule(s) "
                f"({', '.join(r.rule_id for r in blocks)})."
            )
            precedence_steps.append(
                PrecedenceResolutionStep(
                    stage="block_precedence",
                    description="BLOCK rules take precedence over ESCALATE and ALLOW.",
                    matched_rule_ids=sorted(r.rule_id for r in blocks),
                    outcome=outcome,
                )
            )
        elif escalations:
            outcome = DecisionOutcome.ESCALATE_FOR_HUMAN_REVIEW
            precedence_explanation = (
                "No BLOCK rules matched. One or more ESCALATE rules matched, "
                "so manual review is required before execution."
            )
            summary = (
                "ESCALATE_FOR_HUMAN_REVIEW for "
                f"rule(s) ({', '.join(r.rule_id for r in escalations)})."
            )
            precedence_steps.append(
                PrecedenceResolutionStep(
                    stage="escalate_precedence",
                    description="No BLOCK rules matched; ESCALATE rules require manual review.",
                    matched_rule_ids=sorted(r.rule_id for r in escalations),
                    outcome=outcome,
                )
            )
        else:
            precedence_steps.append(
                PrecedenceResolutionStep(
                    stage="default_precedence",
                    description=(
                        "No higher-precedence rule class matched. Applied configured default decision."
                    ),
                    outcome=outcome,
                )
            )

        if schema_errors:
            outcome = DecisionOutcome.BLOCKED
            precedence_explanation = "Context schema validation failed before policy evaluation; blocked deterministically."
            summary = (
                "BLOCKED due to context schema errors: "
                f"{'; '.join(schema_errors)}"
            )
            precedence_steps.append(
                PrecedenceResolutionStep(
                    stage="schema_validation_guardrail",
                    description="Schema validation failed; forcing BLOCKED outcome.",
                    outcome=outcome,
                )
            )
        if identity_errors:
            outcome = DecisionOutcome.BLOCKED
            missing_fields.update(identity_errors)
            precedence_explanation = "Strict mode requires actor identity context fields before policy evaluation."
            summary = (
                "BLOCKED due to missing identity field(s): "
                f"{', '.join(identity_errors)}"
            )
            precedence_steps.append(
                PrecedenceResolutionStep(
                    stage="identity_validation_guardrail",
                    description="Strict identity validation failed; forcing BLOCKED outcome.",
                    outcome=outcome,
                )
            )
        if ai_metadata_errors:
            outcome = DecisionOutcome.BLOCKED
            missing_fields.update(ai_metadata_errors)
            precedence_explanation = "AI-originated action proposals require deterministic governance metadata before policy evaluation."
            summary = (
                "BLOCKED due to missing AI-governance field(s): "
                f"{', '.join(ai_metadata_errors)}"
            )
            precedence_steps.append(
                PrecedenceResolutionStep(
                    stage="ai_metadata_validation_guardrail",
                    description="AI-governance metadata validation failed; forcing BLOCKED outcome.",
                    outcome=outcome,
                )
            )
        if self.config.require_allow_match and not allows and not matched_invariants:
            outcome = DecisionOutcome.BLOCKED
            if not matched:
                precedence_explanation = (
                    "Strict allow mode is enabled and no rules matched. "
                    "At least one ALLOW rule must match."
                )
                summary = (
                    "BLOCKED because no matching policy rules were "
                    "found under strict allow mode."
                )
            else:
                precedence_explanation = "Strict allow mode is enabled. Matching rules were found, but none were ALLOW."
                summary = (
                    "BLOCKED because strict allow mode requires at "
                    "least one matching ALLOW rule."
                )
            precedence_steps.append(
                PrecedenceResolutionStep(
                    stage="strict_allow_guardrail",
                    description="Strict allow mode enforced and no ALLOW rule matched.",
                    outcome=outcome,
                )
            )
        if not matched and self.config.default_decision != DecisionOutcome.APPROVED:
            summary = (
                f"{outcome.value} because no matching policy rules "
                f"were found under {self.config.default_decision.value.lower()}-by-default mode."
            )
        if conflicting_rules:
            precedence_explanation = (
                f"{precedence_explanation} Multiple conflicting rules matched; "
                "BLOCK takes precedence over ESCALATE and ALLOW."
            )
            precedence_steps.append(
                PrecedenceResolutionStep(
                    stage="conflict_resolution",
                    description="Resolved conflicting rule decisions via deterministic precedence.",
                    matched_rule_ids=conflicting_rules,
                    outcome=outcome,
                )
            )
        return (
            outcome,
            precedence_explanation,
            summary,
            matched,
            matched_invariants,
            conflicting_rules,
        )

    def _assemble_reasoning(
        self,
        *,
        proposal: ActionProposal,
        outcome: DecisionOutcome,
        precedence_explanation: str,
        matched: list[RuleEvaluationResult],
        matched_invariants: list[InvariantEvaluationResult],
        schema_errors: list[str],
        identity_errors: list[str],
        ai_metadata_errors: list[str],
        evaluated_exceptions: list[ExceptionEvaluationResult],
        overlay_note: str | None,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object], list[str], list[str]]:
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
                "control_ids": next(
                    (
                        list(rule.control_ids)
                        for rule in self.rules
                        if rule.id == result.rule_id
                    ),
                    [],
                ),
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
            outcome_rationale.append(
                "Invariant violations are enforced before ordinary rule precedence."
            )
        if schema_errors:
            outcome_rationale.append(
                "Input context schema validation failed before rule evaluation."
            )
        if identity_errors:
            outcome_rationale.append(
                "Strict identity checks failed before rule evaluation."
            )
        if ai_metadata_errors:
            outcome_rationale.append(
                "AI-originated metadata checks failed before rule evaluation."
            )
        if any(result.missing_evidence for result in matched):
            outcome_rationale.append(
                "Missing governance evidence influenced one or more matched AI-assisted controls."
            )
        if evaluated_exceptions:
            outcome_rationale.append(
                "Exception overlay stage executed deterministically after baseline evaluation."
            )
        if overlay_note:
            outcome_rationale.append(overlay_note)
        reviewer_guidance = [
            "Verify matched controls align with control owner expectations.",
            "Retain decision hash and input fingerprint for audit replay.",
        ]
        if outcome == DecisionOutcome.ESCALATE_FOR_HUMAN_REVIEW:
            reviewer_guidance.append(
                "Manual approval is required before action execution."
            )
        if outcome == DecisionOutcome.BLOCKED:
            reviewer_guidance.append(
                "Treat as control failure until remediating evidence is attached."
            )
        return (
            matched_controls,
            matched_invariant_controls,
            risk_summary,
            outcome_rationale,
            reviewer_guidance,
        )

    @staticmethod
    def _assemble_audit_record(
        *,
        proposal: ActionProposal,
        decision_id: str,
        decision_timestamp: datetime,
        outcome: DecisionOutcome,
        policy_bundle: PolicyBundleMetadata,
        matched: list[RuleEvaluationResult],
        evaluated: list[RuleEvaluationResult],
        missing_fields: set[str],
        precedence_explanation: str,
        input_fingerprint: str,
        decision_hash: str,
        baseline_outcome: DecisionOutcome,
        applied_exceptions: list[ExceptionEvaluationResult],
        evaluated_exceptions: list[ExceptionEvaluationResult],
        canonical_replay_payload: dict[str, object],
    ) -> tuple[AuditRecord, dict[str, object]]:
        source_metadata = {
            key: value
            for key, value in proposal.attributes.items()
            if key.startswith("source_")
            or key.startswith("servicenow_")
            or key.startswith("jira_")
        }
        event_type = str(
            source_metadata.get("source_event_type") or "decision.evaluated"
        )
        operational_metadata = {
            "decision_id": decision_id,
            "decision_timestamp": decision_timestamp.isoformat(),
            "event_type": event_type,
        }
        downstream_outcome_raw = proposal.attributes.get("downstream_outcome")
        downstream_outcome = (
            str(downstream_outcome_raw).strip().lower()
            if downstream_outcome_raw is not None
            else None
        )
        if downstream_outcome not in {"success", "failure"}:
            downstream_outcome = None
        incident_flag_raw = proposal.attributes.get("incident_flag")
        incident_flag = incident_flag_raw if isinstance(incident_flag_raw, bool) else None

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
            policy_bundle=policy_bundle,
            matched_rule_ids=[r.rule_id for r in matched],
            evaluated_rule_ids=[r.rule_id for r in evaluated],
            missing_fields=sorted(missing_fields),
            precedence_explanation=precedence_explanation,
            input_fingerprint=input_fingerprint,
            decision_hash=decision_hash,
            baseline_outcome=baseline_outcome,
            applied_exception_ids=[r.exception_id for r in applied_exceptions],
            evaluated_exception_ids=[r.exception_id for r in evaluated_exceptions],
            source_metadata=source_metadata,
            request_correlation_id=proposal.request_id,
            evaluator_version=SENA_VERSION,
            policy_bundle_release_id=policy_bundle.version,
            downstream_outcome=downstream_outcome,
            incident_flag=incident_flag,
            canonical_replay_payload=canonical_replay_payload,
            operational_metadata=operational_metadata,
        )
        return audit_record, operational_metadata

    def evaluate(self, proposal: ActionProposal, facts: dict) -> EvaluationTrace:
        context = self._build_context(proposal, facts)
        applicable = [r for r in self.rules if proposal.action_type in r.applies_to]
        applicable_invariants = [
            invariant
            for invariant in self.invariants
            if proposal.action_type in invariant.applies_to
        ]
        evaluated: list[RuleEvaluationResult] = []
        evaluated_invariants: list[InvariantEvaluationResult] = []
        precedence_steps: list[PrecedenceResolutionStep] = [
            PrecedenceResolutionStep(
                stage="start",
                description="Started deterministic policy evaluation.",
            )
        ]
        missing_fields: set[str] = set()
        (
            schema_errors,
            identity_errors,
            ai_metadata_errors,
        ) = self._run_pre_evaluation_validation(proposal, context)

        if not schema_errors and not identity_errors:
            evaluated_invariants = self._evaluate_invariants(
                applicable_invariants, context, missing_fields
            )
            evaluated = self._evaluate_rules(
                applicable=applicable,
                proposal=proposal,
                context=context,
                missing_fields=missing_fields,
            )
            precedence_steps.append(
                PrecedenceResolutionStep(
                    stage="rule_evaluation",
                    description=(
                        "Evaluated all applicable rules and captured matched/non-matched outcomes."
                    ),
                    matched_rule_ids=sorted(
                        result.rule_id for result in evaluated if result.matched
                    ),
                )
            )
        else:
            evaluated = self._build_skipped_rule_results(
                applicable, "pre_evaluation_validation_failed"
            )
            precedence_steps.append(
                PrecedenceResolutionStep(
                    stage="rule_evaluation_skipped",
                    description=(
                        "Rule condition evaluation skipped due to deterministic pre-evaluation validation errors."
                    ),
                )
            )
        (
            outcome,
            precedence_explanation,
            summary,
            matched,
            matched_invariants,
            conflicting_rules,
        ) = self._resolve_precedence(
            proposal=proposal,
            evaluated=evaluated,
            evaluated_invariants=evaluated_invariants,
            schema_errors=schema_errors,
            identity_errors=identity_errors,
            ai_metadata_errors=ai_metadata_errors,
            missing_fields=missing_fields,
            precedence_steps=precedence_steps,
        )

        decision_timestamp = datetime.now(timezone.utc)
        baseline_outcome = outcome
        (
            outcome,
            evaluated_exceptions,
            applied_exceptions,
            overlay_note,
        ) = self._apply_exception_overlay(
            proposal=proposal,
            baseline_outcome=baseline_outcome,
            decision_time=decision_timestamp,
        )
        if overlay_note:
            precedence_explanation = f"{precedence_explanation} {overlay_note}"
            summary = (
                f"{outcome.value}. "
                f"Baseline was {baseline_outcome.value}."
            )
            precedence_steps.append(
                PrecedenceResolutionStep(
                    stage="exception_overlay",
                    description=overlay_note,
                    matched_rule_ids=sorted(
                        result.exception_id for result in applied_exceptions
                    ),
                    outcome=outcome,
                )
            )
        (
            matched_controls,
            matched_invariant_controls,
            risk_summary,
            outcome_rationale,
            reviewer_guidance,
        ) = self._assemble_reasoning(
            proposal=proposal,
            outcome=outcome,
            precedence_explanation=precedence_explanation,
            matched=matched,
            matched_invariants=matched_invariants,
            schema_errors=schema_errors,
            identity_errors=identity_errors,
            ai_metadata_errors=ai_metadata_errors,
            evaluated_exceptions=evaluated_exceptions,
            overlay_note=overlay_note,
        )

        canonical_payload = {
            "proposal": {
                "action_type": proposal.action_type,
                "request_id": proposal.request_id,
                "actor_id": proposal.actor_id,
                "actor_role": proposal.actor_role,
                "attributes": proposal.attributes,
                "action_origin": proposal.action_origin.value,
                "ai_metadata": asdict(proposal.ai_metadata)
                if proposal.ai_metadata
                else None,
                "autonomous_metadata": asdict(proposal.autonomous_metadata)
                if proposal.autonomous_metadata
                else None,
            },
            "facts": facts,
        }
        input_fingerprint = hashlib.sha256(
            json.dumps(canonical_payload, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
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
                    "matched_invariant_ids": sorted(
                        r.invariant_id for r in matched_invariants
                    ),
                    "evaluated_exception_ids": sorted(
                        result.exception_id for result in evaluated_exceptions
                    ),
                    "applied_exception_ids": sorted(
                        result.exception_id for result in applied_exceptions
                    ),
                    "outcome": outcome.value,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        canonical_replay_payload = {
            "schema_version": "1",
            "input_fingerprint": input_fingerprint,
            "policy_bundle": {
                "bundle_name": self.policy_bundle.bundle_name,
                "version": self.policy_bundle.version,
                "schema_version": self.policy_bundle.schema_version,
            },
            "proposal": canonical_payload["proposal"],
            "facts": canonical_payload["facts"],
            "outcome": outcome.value,
            "baseline_outcome": baseline_outcome.value,
            "decision_hash": decision_hash,
            "matched_rule_ids": sorted(r.rule_id for r in matched),
            "matched_invariant_ids": sorted(
                r.invariant_id for r in matched_invariants
            ),
            "evaluated_exception_ids": sorted(
                item.exception_id for item in evaluated_exceptions
            ),
            "applied_exception_ids": sorted(
                item.exception_id for item in applied_exceptions
            ),
            "missing_fields": sorted(missing_fields),
            "conflicting_rules": conflicting_rules,
            "precedence_steps": [
                {
                    "stage": step.stage,
                    "description": self._stable_summary(step.description),
                    "matched_rule_ids": sorted(step.matched_rule_ids),
                    "outcome": step.outcome.value if step.outcome else None,
                }
                for step in precedence_steps
            ],
            "reasoning": {
                "precedence_explanation": self._stable_summary(
                    precedence_explanation
                ),
                "summary": self._stable_summary(summary),
                "outcome_rationale": [
                    self._stable_summary(item) for item in outcome_rationale
                ],
                "reviewer_guidance": [
                    self._stable_summary(item) for item in reviewer_guidance
                ],
                "matched_controls": matched_controls,
                "matched_invariants": matched_invariant_controls,
                "risk_summary": risk_summary,
            },
        }
        decision_id = (
            f"dec_{decision_hash[:12]}"
            if self.config.deterministic_mode
            else f"dec_{uuid.uuid4().hex[:12]}"
        )
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
            exception_summary={
                "baseline_outcome": baseline_outcome.value,
                "evaluated_exception_ids": [
                    item.exception_id for item in evaluated_exceptions
                ],
                "applied_exception_ids": [
                    item.exception_id for item in applied_exceptions
                ],
            },
        )

        audit_record, operational_metadata = self._assemble_audit_record(
            proposal=proposal,
            decision_id=decision_id,
            decision_timestamp=decision_timestamp,
            outcome=outcome,
            policy_bundle=self.policy_bundle,
            matched=matched,
            evaluated=evaluated,
            missing_fields=missing_fields,
            precedence_explanation=precedence_explanation,
            input_fingerprint=input_fingerprint,
            decision_hash=decision_hash,
            baseline_outcome=baseline_outcome,
            applied_exceptions=applied_exceptions,
            evaluated_exceptions=evaluated_exceptions,
            canonical_replay_payload=canonical_replay_payload,
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
            baseline_outcome=baseline_outcome,
            evaluated_exceptions=evaluated_exceptions,
            applied_exceptions=applied_exceptions,
            conflicting_rules=conflicting_rules,
            precedence_steps=precedence_steps,
            missing_fields=sorted(missing_fields),
            context=context,
            audit_record=audit_record,
            canonical_replay_payload=canonical_replay_payload,
            operational_metadata=operational_metadata,
        )
        if (
            trace.outcome == DecisionOutcome.ESCALATE_FOR_HUMAN_REVIEW
            and self.config.on_escalation is not None
        ):
            self.config.on_escalation(trace)
        return trace
