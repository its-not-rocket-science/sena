from datetime import datetime, timedelta, timezone

from sena.core.enums import ActionOrigin, DecisionOutcome, RuleDecision, Severity
from sena.core.models import (
    ActionProposal,
    EvaluatorConfig,
    ExceptionScope,
    InvariantEvaluationResult,
    PolicyBundleMetadata,
    PolicyException,
    PolicyInvariant,
    PolicyRule,
    PrecedenceResolutionStep,
    RuleEvaluationResult,
)
from sena.engine.evaluator import PolicyEvaluator


def _rule(*, decision: RuleDecision = RuleDecision.ALLOW) -> PolicyRule:
    return PolicyRule(
        id="r-1",
        description="base rule",
        severity=Severity.MEDIUM,
        inviolable=False,
        applies_to=["deploy"],
        condition={"field": "risk", "eq": "low"},
        decision=decision,
        reason="matched",
    )


def test_pre_evaluation_validation_isolated() -> None:
    evaluator = PolicyEvaluator(
        [_rule()],
        policy_bundle=PolicyBundleMetadata(
            bundle_name="bundle",
            version="1",
            loaded_from="tests",
            context_schema={"amount": "int"},
        ),
        config=EvaluatorConfig(require_allow_match=True),
    )
    proposal = ActionProposal(
        action_type="deploy",
        action_origin=ActionOrigin.AI_SUGGESTED,
        attributes={"amount": "invalid"},
    )

    context = evaluator._build_context(proposal, {})
    schema_errors, identity_errors, ai_metadata_errors = evaluator._run_pre_evaluation_validation(
        proposal, context
    )

    assert schema_errors
    assert "actor_id" in identity_errors
    assert "ai_metadata" in ai_metadata_errors


def test_invariant_evaluation_isolated() -> None:
    invariant = PolicyInvariant(
        id="inv-1",
        description="must be production",
        applies_to=["deploy"],
        condition={"field": "impact", "eq": "production"},
        reason="production invariant",
    )
    missing_fields: set[str] = set()

    results = PolicyEvaluator._evaluate_invariants(
        [invariant], {"impact": "production"}, missing_fields
    )

    assert len(results) == 1
    assert results[0].matched is True
    assert results[0].reason == "production invariant"


def test_rule_matching_and_evidence_checks_isolated() -> None:
    evidence_rule = PolicyRule(
        id="r-evidence",
        description="requires evidence",
        severity=Severity.HIGH,
        inviolable=False,
        applies_to=["deploy"],
        condition={"field": "risk", "eq": "low"},
        decision=RuleDecision.ALLOW,
        reason="allow with evidence",
        required_evidence=["source_citations", "human_owner"],
        missing_evidence_decision=RuleDecision.BLOCK,
    )
    evaluator = PolicyEvaluator([evidence_rule])
    proposal = ActionProposal(
        action_type="deploy",
        action_origin=ActionOrigin.AI_SUGGESTED,
        attributes={"risk": "low"},
    )
    missing_fields: set[str] = set()

    evaluated = evaluator._evaluate_rules(
        applicable=[evidence_rule],
        proposal=proposal,
        context=evaluator._build_context(proposal, {}),
        missing_fields=missing_fields,
    )

    assert evaluated[0].matched is True
    assert evaluated[0].decision == RuleDecision.BLOCK
    assert set(evaluated[0].missing_evidence) == {"source_citations", "human_owner"}
    assert "evidence.source_citations" in missing_fields


def test_precedence_resolution_isolated() -> None:
    evaluator = PolicyEvaluator([_rule(decision=RuleDecision.ESCALATE)])
    missing_fields: set[str] = set()
    steps = [
        PrecedenceResolutionStep(
            stage="start", description="Started deterministic policy evaluation."
        )
    ]
    evaluated = [
        RuleEvaluationResult(
            rule_id="r-escalate",
            matched=True,
            decision=RuleDecision.ESCALATE,
            reason="needs review",
        )
    ]

    outcome, explanation, summary, matched, _, _ = evaluator._resolve_precedence(
        proposal=ActionProposal(action_type="deploy"),
        evaluated=evaluated,
        evaluated_invariants=[
            InvariantEvaluationResult(invariant_id="inv-1", matched=False)
        ],
        schema_errors=[],
        identity_errors=[],
        ai_metadata_errors=[],
        missing_fields=missing_fields,
        precedence_steps=steps,
    )

    assert outcome == DecisionOutcome.ESCALATE_FOR_HUMAN_REVIEW
    assert "manual review" in explanation.lower()
    assert matched
    assert "ESCALATE_FOR_HUMAN_REVIEW" in summary


def test_exception_overlay_isolated() -> None:
    evaluator = PolicyEvaluator([_rule()])
    exception = PolicyException(
        exception_id="exc-1",
        scope=ExceptionScope(action_type="deploy"),
        expiry=datetime.now(timezone.utc) + timedelta(hours=1),
        approver_class="security",
        justification="temporary",
        approved_by="owner",
        approved_at=datetime.now(timezone.utc),
    )
    evaluator.exceptions = [exception]

    outcome, evaluated, applied, overlay_note = evaluator._apply_exception_overlay(
        proposal=ActionProposal(action_type="deploy"),
        baseline_outcome=DecisionOutcome.ESCALATE_FOR_HUMAN_REVIEW,
        decision_time=datetime.now(timezone.utc),
    )

    assert outcome == DecisionOutcome.APPROVED
    assert evaluated and applied
    assert overlay_note is not None


def test_reasoning_and_audit_assembly_isolated() -> None:
    evaluator = PolicyEvaluator([_rule()])
    matched_rule = RuleEvaluationResult(
        rule_id="r-1",
        matched=True,
        decision=RuleDecision.ALLOW,
        reason="matched",
    )
    matched_controls, _, _, rationale, _ = evaluator._assemble_reasoning(
        proposal=ActionProposal(action_type="deploy", attributes={"risk": "low"}),
        outcome=DecisionOutcome.APPROVED,
        precedence_explanation="explanation",
        matched=[matched_rule],
        matched_invariants=[],
        schema_errors=[],
        identity_errors=[],
        ai_metadata_errors=[],
        evaluated_exceptions=[],
        overlay_note=None,
    )

    audit_record, operational_metadata = evaluator._assemble_audit_record(
        proposal=ActionProposal(
            action_type="deploy",
            request_id="req-1",
            attributes={"source_event_type": "decision.evaluated", "incident_flag": True},
        ),
        decision_id="dec-1",
        decision_timestamp=datetime.now(timezone.utc),
        outcome=DecisionOutcome.APPROVED,
        policy_bundle=evaluator.policy_bundle,
        matched=[matched_rule],
        evaluated=[matched_rule],
        missing_fields=set(),
        precedence_explanation="explanation",
        input_fingerprint="abc",
        decision_hash="def",
        baseline_outcome=DecisionOutcome.APPROVED,
        applied_exceptions=[],
        evaluated_exceptions=[],
        canonical_replay_payload={},
    )

    assert matched_controls
    assert rationale[0].startswith("Outcome resolved")
    assert audit_record.request_id == "req-1"
    assert operational_metadata["event_type"] == "decision.evaluated"
