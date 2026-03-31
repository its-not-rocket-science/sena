from sena.core.enums import DecisionOutcome
from sena.core.models import ActionProposal
from sena.engine.evaluator import PolicyEvaluator
from sena.policy.parser import load_policies_from_dir


def test_export_requires_review() -> None:
    evaluator = PolicyEvaluator(load_policies_from_dir("src/sena/examples/policies"))
    proposal = ActionProposal(
        action_type="export_customer_data",
        attributes={
            "requested_fields": ["customer_id", "date_of_birth"],
            "legal_basis": "contract",
            "dpo_approved": False,
        },
    )

    trace = evaluator.evaluate(proposal, {})
    assert trace.outcome == DecisionOutcome.ESCALATE_FOR_HUMAN_REVIEW
