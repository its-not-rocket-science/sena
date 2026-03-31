from sena.core.enums import DecisionOutcome
from sena.core.models import ActionProposal
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
    assert trace.policy_bundle.bundle_name == "default-bundle"


def test_no_match_defaults_to_approved() -> None:
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    evaluator = PolicyEvaluator(rules, policy_bundle=metadata)
    proposal = ActionProposal(action_type="nonexistent_action", attributes={"x": 1})

    trace = evaluator.evaluate(proposal, {})

    assert trace.outcome == DecisionOutcome.APPROVED
    assert "approved" in trace.summary.lower()
    assert trace.matched_rules == []
