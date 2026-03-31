"""Basic usage for the supported compliance engine path."""

from sena.core.models import ActionProposal
from sena.engine.evaluator import PolicyEvaluator
from sena.policy.parser import load_policy_bundle

rules, metadata = load_policy_bundle(
    "src/sena/examples/policies",
    bundle_name="example-bundle",
    version="2026.03",
)
evaluator = PolicyEvaluator(rules, policy_bundle=metadata)

proposal = ActionProposal(
    action_type="approve_vendor_payment",
    request_id="req-demo-001",
    actor_id="user-42",
    attributes={
        "amount": 7500,
        "vendor_verified": True,
        "requester_role": "finance_analyst",
    },
)

trace = evaluator.evaluate(proposal, facts={"country": "US"})
print(trace.to_dict())
