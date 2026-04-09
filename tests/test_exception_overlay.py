from datetime import datetime, timedelta, timezone

from sena.core.enums import DecisionOutcome, RuleDecision, Severity
from sena.core.models import ActionProposal, ExceptionScope, PolicyException, PolicyRule
from sena.engine.evaluator import PolicyEvaluator


def _escalation_rule() -> PolicyRule:
    return PolicyRule(
        id="esc_high_value",
        description="Escalate high-value requests",
        severity=Severity.HIGH,
        inviolable=False,
        applies_to=["approve_vendor_payment"],
        condition={"field": "amount", "gte": 1000},
        decision=RuleDecision.ESCALATE,
        reason="requires manual review",
    )


def test_exception_overlay_changes_outcome_and_hash_is_replay_stable() -> None:
    now = datetime.now(timezone.utc)
    exception = PolicyException(
        exception_id="exc-1",
        scope=ExceptionScope(
            action_type="approve_vendor_payment",
            actor="user-1",
            attributes={"vendor_verified": True},
        ),
        expiry=now + timedelta(days=1),
        approver_class="finance_director",
        justification="Emergency payroll run",
        approved_by="director-9",
        approved_at=now,
    )
    evaluator = PolicyEvaluator([_escalation_rule()], exceptions=[exception])
    proposal = ActionProposal(
        action_type="approve_vendor_payment",
        actor_id="user-1",
        attributes={"amount": 2000, "vendor_verified": True},
    )

    first = evaluator.evaluate(proposal, {})
    second = evaluator.evaluate(proposal, {})

    assert first.baseline_outcome == DecisionOutcome.ESCALATE_FOR_HUMAN_REVIEW
    assert first.outcome == DecisionOutcome.APPROVED
    assert first.decision_hash == second.decision_hash
    assert [item.exception_id for item in first.applied_exceptions] == ["exc-1"]


def test_expired_exception_is_ignored_deterministically() -> None:
    now = datetime.now(timezone.utc)
    expired = PolicyException(
        exception_id="exc-expired",
        scope=ExceptionScope(action_type="approve_vendor_payment", actor="user-1"),
        expiry=now - timedelta(minutes=1),
        approver_class="finance_director",
        justification="Expired",
        approved_by="director-1",
        approved_at=now - timedelta(days=1),
    )
    evaluator = PolicyEvaluator([_escalation_rule()], exceptions=[expired])
    proposal = ActionProposal(
        action_type="approve_vendor_payment",
        actor_id="user-1",
        attributes={"amount": 2000},
    )

    trace = evaluator.evaluate(proposal, {})

    assert trace.outcome == DecisionOutcome.ESCALATE_FOR_HUMAN_REVIEW
    assert trace.baseline_outcome == DecisionOutcome.ESCALATE_FOR_HUMAN_REVIEW
    assert trace.applied_exceptions == []
    assert trace.evaluated_exceptions[0].expired is True
