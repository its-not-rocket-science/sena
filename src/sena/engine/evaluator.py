from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sena import __version__ as SENA_VERSION
from sena.core.enums import DecisionOutcome
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
from sena.engine.evaluator_components import (
    apply_exception_overlay,
    assemble_audit_record,
    assemble_reasoning_payload,
    build_canonical_decision_artifacts,
    build_context,
    build_skipped_rule_results,
    evaluate_invariants,
    evaluate_rules,
    resolve_precedence,
    run_pre_evaluation_validation,
    scope_matches,
    stable_summary,
)
from sena.policy.schema_evolution import evaluate_bundle_compatibility

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
        return scope_matches(scope, proposal)

    @staticmethod
    def _stable_summary(text: str) -> str:
        return stable_summary(text)

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
        return apply_exception_overlay(
            exceptions=self.exceptions,
            proposal=proposal,
            baseline_outcome=baseline_outcome,
            decision_time=decision_time,
        )

    @staticmethod
    def _build_context(proposal: ActionProposal, facts: dict) -> dict[str, object]:
        return build_context(proposal, facts)

    def _run_pre_evaluation_validation(
        self, proposal: ActionProposal, context: dict[str, object]
    ) -> tuple[list[str], list[str], list[str]]:
        validation = run_pre_evaluation_validation(
            proposal=proposal,
            context=context,
            require_allow_match=self.config.require_allow_match,
            enforce_context_schema=self.config.enforce_context_schema,
            context_schema=self.policy_bundle.context_schema,
        )
        return (
            validation.schema_errors,
            validation.identity_errors,
            validation.ai_metadata_errors,
        )

    @staticmethod
    def _evaluate_invariants(
        applicable_invariants: list[PolicyInvariant],
        context: dict[str, object],
        missing_fields: set[str],
    ) -> list[InvariantEvaluationResult]:
        return evaluate_invariants(
            applicable_invariants=applicable_invariants,
            context=context,
            missing_fields=missing_fields,
        )

    def _evaluate_rules(
        self,
        *,
        applicable: list[PolicyRule],
        proposal: ActionProposal,
        context: dict[str, object],
        missing_fields: set[str],
    ) -> list[RuleEvaluationResult]:
        return evaluate_rules(
            applicable=applicable,
            proposal=proposal,
            context=context,
            missing_fields=missing_fields,
        )

    @staticmethod
    def _build_skipped_rule_results(
        applicable: list[PolicyRule], skip_reason: str
    ) -> list[RuleEvaluationResult]:
        return build_skipped_rule_results(applicable=applicable, skip_reason=skip_reason)

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
        resolution = resolve_precedence(
            proposal=proposal,
            default_decision=self.config.default_decision,
            require_allow_match=self.config.require_allow_match,
            evaluated=evaluated,
            evaluated_invariants=evaluated_invariants,
            schema_errors=schema_errors,
            identity_errors=identity_errors,
            ai_metadata_errors=ai_metadata_errors,
            missing_fields=missing_fields,
            precedence_steps=precedence_steps,
        )
        return (
            resolution.outcome,
            resolution.precedence_explanation,
            resolution.summary,
            resolution.matched,
            resolution.matched_invariants,
            resolution.conflicting_rules,
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
        return assemble_reasoning_payload(
            proposal=proposal,
            outcome=outcome,
            precedence_explanation=precedence_explanation,
            matched=matched,
            rules=self.rules,
            matched_invariants=matched_invariants,
            schema_errors=schema_errors,
            identity_errors=identity_errors,
            ai_metadata_errors=ai_metadata_errors,
            evaluated_exceptions=evaluated_exceptions,
            overlay_note=overlay_note,
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
        assembled = assemble_audit_record(
            proposal=proposal,
            decision_id=decision_id,
            decision_timestamp=decision_timestamp,
            outcome=outcome,
            policy_bundle=policy_bundle,
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
        return assembled.audit_record, assembled.operational_metadata

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

        canonical_artifacts = build_canonical_decision_artifacts(
            proposal=proposal,
            facts=facts,
            policy_bundle=self.policy_bundle,
            matched=matched,
            matched_invariants=matched_invariants,
            evaluated_exceptions=evaluated_exceptions,
            applied_exceptions=applied_exceptions,
            outcome=outcome,
            baseline_outcome=baseline_outcome,
            missing_fields=missing_fields,
            conflicting_rules=conflicting_rules,
            precedence_steps=precedence_steps,
            precedence_explanation=precedence_explanation,
            summary=summary,
            matched_controls=matched_controls,
            matched_invariant_controls=matched_invariant_controls,
            risk_summary=risk_summary,
            outcome_rationale=outcome_rationale,
            reviewer_guidance=reviewer_guidance,
        )
        canonical_replay_payload = canonical_artifacts.canonical_replay_payload
        input_fingerprint = canonical_artifacts.input_fingerprint
        decision_hash = canonical_artifacts.decision_hash
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
