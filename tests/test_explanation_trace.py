from sena.core.models import ActionProposal
from sena.engine.evaluator import PolicyEvaluator
from sena.engine.explain import build_explanation
from sena.policy.parser import load_policy_bundle


def test_trace_includes_all_evaluated_rules_with_condition_results() -> None:
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    evaluator = PolicyEvaluator(rules, policy_bundle=metadata)
    trace = evaluator.evaluate(
        ActionProposal(
            action_type="approve_vendor_payment",
            actor_role="finance_analyst",
            attributes={"amount": 15000, "vendor_verified": True},
        ),
        {},
    )

    assert trace.evaluated_rules
    assert len(trace.evaluated_rules) == len(trace.applicable_rules)
    by_rule = {item.rule_id: item for item in trace.evaluated_rules}
    for rule_id in trace.applicable_rules:
        assert rule_id in by_rule
        assert isinstance(by_rule[rule_id].condition_missing_fields, list)


def test_explanation_generator_supports_analyst_and_auditor_views() -> None:
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    evaluator = PolicyEvaluator(rules, policy_bundle=metadata)
    trace = evaluator.evaluate(
        ActionProposal(
            action_type="approve_vendor_payment",
            actor_role="finance_analyst",
            attributes={"amount": 15000, "vendor_verified": True},
        ),
        {},
    )

    analyst = build_explanation(trace, view="analyst")
    auditor = build_explanation(trace, view="auditor")

    assert analyst["view"] == "analyst"
    assert "analyst_summary" in analyst
    assert auditor["view"] == "auditor"
    assert "auditor_trace" in auditor
    assert auditor["auditor_trace"]["precedence_resolution"]
