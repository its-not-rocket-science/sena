from sena.core.models import ActionProposal
from sena.engine.evaluator import PolicyEvaluator
from sena.policy.parser import load_policies_from_dir


def test_blocked_payment_scenario_flags_inviolable_block() -> None:
    evaluator = PolicyEvaluator(load_policies_from_dir("src/sena/examples/policies"))
    proposal = ActionProposal(
        action_type="approve_vendor_payment",
        attributes={
            "amount": 15000,
            "vendor_verified": False,
            "requester_role": "finance_analyst",
        },
    )

    trace = evaluator.evaluate(proposal, {})
    assert trace.outcome.value == "BLOCKED"
    assert "inviolable" in trace.summary.lower()
    assert len(trace.evaluated_rules) == 2
