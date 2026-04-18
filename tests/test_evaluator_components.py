from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sena.core.enums import ActionOrigin, DecisionOutcome, RuleDecision, Severity
from sena.core.models import (
    AIActionMetadata,
    ActionProposal,
    ExceptionScope,
    PolicyBundleMetadata,
    PolicyException,
    PolicyRule,
    PrecedenceResolutionStep,
    RuleEvaluationResult,
)
from sena.engine.evaluator_components import (
    apply_exception_overlay,
    build_canonical_decision_artifacts,
    run_pre_evaluation_validation,
)


def test_component_pre_validation_contract_fields() -> None:
    proposal = ActionProposal(
        action_type="deploy",
        action_origin=ActionOrigin.AI_SUGGESTED,
        ai_metadata=AIActionMetadata(originating_system="assistant"),
    )
    result = run_pre_evaluation_validation(
        proposal=proposal,
        context={"amount": "1"},
        require_allow_match=True,
        enforce_context_schema=True,
        context_schema={"amount": "int"},
    )

    assert "actor_id" in result.identity_errors
    assert result.schema_errors


def test_component_exception_overlay_contract() -> None:
    now = datetime.now(timezone.utc)
    exception = PolicyException(
        exception_id="exc-1",
        scope=ExceptionScope(action_type="deploy", actor="u-1"),
        expiry=now + timedelta(minutes=5),
        approver_class="security",
        justification="temp",
        approved_by="a",
        approved_at=now,
    )

    outcome, evaluated, applied, note = apply_exception_overlay(
        exceptions=[exception],
        proposal=ActionProposal(action_type="deploy", actor_id="u-1"),
        baseline_outcome=DecisionOutcome.ESCALATE_FOR_HUMAN_REVIEW,
        decision_time=now,
    )

    assert outcome == DecisionOutcome.APPROVED
    assert len(evaluated) == 1
    assert [item.exception_id for item in applied] == ["exc-1"]
    assert note is not None


def test_component_canonical_artifacts_include_normalized_reasoning() -> None:
    proposal = ActionProposal(
        action_type="deploy",
        action_origin=ActionOrigin.HUMAN,
        attributes={"risk": "low"},
    )
    matched = [
        RuleEvaluationResult(
            rule_id="r1",
            matched=True,
            decision=RuleDecision.ALLOW,
            inviolable=False,
            reason="ok",
        )
    ]
    artifacts = build_canonical_decision_artifacts(
        proposal=proposal,
        facts={},
        policy_bundle=PolicyBundleMetadata(
            bundle_name="bundle",
            version="1",
            loaded_from="tests",
        ),
        matched=matched,
        matched_invariants=[],
        evaluated_exceptions=[],
        applied_exceptions=[],
        outcome=DecisionOutcome.APPROVED,
        baseline_outcome=DecisionOutcome.APPROVED,
        missing_fields=set(),
        conflicting_rules=[],
        precedence_steps=[
            PrecedenceResolutionStep(
                stage="start", description="Started\n deterministic  policy evaluation."
            )
        ],
        precedence_explanation="Line one\n line two",
        summary="approved",
        matched_controls=[{"rule_id": "r1"}],
        matched_invariant_controls=[],
        risk_summary={},
        outcome_rationale=["First\n rationale"],
        reviewer_guidance=["Keep\n record"],
    )

    assert artifacts.canonical_replay_payload["precedence_steps"][0]["description"] == (
        "Started deterministic policy evaluation."
    )
    assert artifacts.canonical_replay_payload["reasoning"]["precedence_explanation"] == (
        "Line one line two"
    )


def test_component_artifacts_hash_changes_with_outcome() -> None:
    proposal = ActionProposal(action_type="deploy")
    kwargs = dict(
        proposal=proposal,
        facts={},
        policy_bundle=PolicyBundleMetadata(
            bundle_name="bundle",
            version="1",
            loaded_from="tests",
        ),
        matched=[],
        matched_invariants=[],
        evaluated_exceptions=[],
        applied_exceptions=[],
        baseline_outcome=DecisionOutcome.APPROVED,
        missing_fields=set(),
        conflicting_rules=[],
        precedence_steps=[],
        precedence_explanation="x",
        summary="y",
        matched_controls=[],
        matched_invariant_controls=[],
        risk_summary={},
        outcome_rationale=[],
        reviewer_guidance=[],
    )
    approved = build_canonical_decision_artifacts(outcome=DecisionOutcome.APPROVED, **kwargs)
    blocked = build_canonical_decision_artifacts(outcome=DecisionOutcome.BLOCKED, **kwargs)

    assert approved.input_fingerprint == blocked.input_fingerprint
    assert approved.decision_hash != blocked.decision_hash


def test_component_keep_rule_evidence_semantics_with_unsupported_class() -> None:
    rule = PolicyRule(
        id="r",
        description="x",
        severity=Severity.MEDIUM,
        inviolable=False,
        applies_to=["deploy"],
        condition={"field": "risk", "eq": "low"},
        decision=RuleDecision.ALLOW,
        reason="ok",
        required_evidence=["not_supported"],
    )
    # Unsupported evidence classes should remain inert in evaluation contract.
    from sena.engine.evaluator_components import evaluate_rules

    missing: set[str] = set()
    results = evaluate_rules(
        applicable=[rule],
        proposal=ActionProposal(
            action_type="deploy", action_origin=ActionOrigin.AI_SUGGESTED, attributes={"risk": "low"}
        ),
        context={"risk": "low", "action_origin": "ai_suggested"},
        missing_fields=missing,
    )
    assert results[0].decision == RuleDecision.ALLOW
    assert not missing
