from sena.core.enums import DecisionOutcome
from sena.core.models import ActionProposal, EvaluatorConfig
from sena.engine.evaluator import PolicyEvaluator
from sena.policy.parser import load_policy_bundle


def test_inviolable_block_beats_escalation_in_conflict() -> None:
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    evaluator = PolicyEvaluator(rules, policy_bundle=metadata)
    proposal = ActionProposal(
        action_type="export_customer_data",
        attributes={
            "requested_fields": ["ssn", "date_of_birth"],
            "legal_basis": "contract",
            "dpo_approved": False,
        },
    )

    trace = evaluator.evaluate(proposal, {})

    assert trace.outcome == DecisionOutcome.BLOCKED
    assert "inviolable" in trace.reasoning.precedence_explanation.lower()
    assert trace.policy_bundle.bundle_name == "enterprise-compliance-controls"
    assert trace.conflicting_rules


def test_no_match_defaults_to_approved() -> None:
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    evaluator = PolicyEvaluator(rules, policy_bundle=metadata)
    proposal = ActionProposal(action_type="nonexistent_action", attributes={"x": 1})

    trace = evaluator.evaluate(proposal, {})

    assert trace.outcome == DecisionOutcome.APPROVED
    assert "approved" in trace.summary.lower()
    assert trace.matched_rules == []


def test_no_match_can_be_deny_by_default() -> None:
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    evaluator = PolicyEvaluator(
        rules,
        policy_bundle=metadata,
        config=EvaluatorConfig(default_decision=DecisionOutcome.BLOCKED),
    )
    proposal = ActionProposal(action_type="nonexistent_action", attributes={"x": 1})

    trace = evaluator.evaluate(proposal, {})

    assert trace.outcome == DecisionOutcome.BLOCKED
    assert "no matching policy rules" in trace.summary.lower()


def test_strict_allow_can_override_escalation_when_no_allow_matches() -> None:
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    evaluator = PolicyEvaluator(
        rules,
        policy_bundle=metadata,
        config=EvaluatorConfig(require_allow_match=True),
    )
    proposal = ActionProposal(
        action_type="export_customer_data",
        attributes={
            "requested_fields": ["date_of_birth"],
            "legal_basis": "contract",
            "dpo_approved": False,
        },
    )

    trace = evaluator.evaluate(proposal, {})

    assert trace.outcome == DecisionOutcome.BLOCKED
    assert "strict allow mode" in trace.reasoning.precedence_explanation.lower()


def test_actor_role_condition_controls_high_value_payment_escalation() -> None:
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    evaluator = PolicyEvaluator(rules, policy_bundle=metadata)

    director_trace = evaluator.evaluate(
        ActionProposal(
            action_type="approve_vendor_payment",
            actor_role="finance_director",
            attributes={"amount": 15000, "vendor_verified": True},
        ),
        {},
    )
    analyst_trace = evaluator.evaluate(
        ActionProposal(
            action_type="approve_vendor_payment",
            actor_role="finance_analyst",
            attributes={"amount": 15000, "vendor_verified": True},
        ),
        {},
    )

    assert director_trace.outcome == DecisionOutcome.APPROVED
    assert analyst_trace.outcome == DecisionOutcome.ESCALATE_FOR_HUMAN_REVIEW


def test_strict_mode_blocks_when_identity_fields_are_missing() -> None:
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    evaluator = PolicyEvaluator(
        rules,
        policy_bundle=metadata,
        config=EvaluatorConfig(require_allow_match=True),
    )

    trace = evaluator.evaluate(
        ActionProposal(
            action_type="approve_vendor_payment",
            attributes={"amount": 500, "vendor_verified": True},
        ),
        {},
    )

    assert trace.outcome == DecisionOutcome.BLOCKED
    assert "actor_id" in trace.missing_fields
    assert "actor_role" in trace.missing_fields
