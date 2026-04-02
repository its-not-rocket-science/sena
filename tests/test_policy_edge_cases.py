import pytest

from sena.core.enums import DecisionOutcome, RuleDecision, Severity
from sena.core.models import (
    ActionProposal,
    EvaluatorConfig,
    PolicyBundleMetadata,
    PolicyRule,
)
from sena.engine.evaluator import PolicyEvaluator
from sena.policy.interpreter import evaluate_condition_with_trace
from sena.policy.parser import PolicyParseError, parse_policy_file


def _rule(
    rule_id: str,
    *,
    condition: dict,
    decision: RuleDecision = RuleDecision.ALLOW,
    inviolable: bool = False,
    applies_to: list[str] | None = None,
) -> PolicyRule:
    return PolicyRule(
        id=rule_id,
        description=f"rule {rule_id}",
        severity=Severity.MEDIUM,
        inviolable=inviolable,
        applies_to=applies_to or ["approve_vendor_payment"],
        condition=condition,
        decision=decision,
        reason=f"{rule_id} matched",
    )


def test_parse_policy_file_rejects_rule_with_unsupported_operator(tmp_path) -> None:
    bad_file = tmp_path / "bad_operator.yaml"
    bad_file.write_text(
        '[{"id":"r1","description":"d","severity":"low","inviolable":false,'
        '"applies_to":["a"],"condition":{"field":"x","bad_op":1},'
        '"decision":"ALLOW","reason":"ok"}]'
    )

    with pytest.raises(PolicyParseError, match="unsupported operator"):
        parse_policy_file(bad_file)


def test_parse_policy_file_rejects_mixed_logical_operators(tmp_path) -> None:
    bad_file = tmp_path / "bad_logic.yaml"
    bad_file.write_text(
        '[{"id":"r1","description":"d","severity":"low","inviolable":false,'
        '"applies_to":["a"],"condition":{"and":[{"field":"x","eq":1}],"or":['
        '{"field":"y","eq":2}]},"decision":"ALLOW","reason":"ok"}]'
    )

    with pytest.raises(PolicyParseError, match="exactly one logical operator"):
        parse_policy_file(bad_file)


def test_parse_policy_file_rejects_invalid_exists_operand_type(tmp_path) -> None:
    bad_file = tmp_path / "bad_exists.yaml"
    bad_file.write_text(
        '[{"id":"r1","description":"d","severity":"low","inviolable":false,'
        '"applies_to":["a"],"condition":{"field":"x","exists":"yes"},'
        '"decision":"ALLOW","reason":"ok"}]'
    )

    with pytest.raises(PolicyParseError, match="exists"):
        parse_policy_file(bad_file)


def test_dsl_not_with_missing_field_tracks_missing_and_inverts_result() -> None:
    condition = {"not": {"field": "actor.department", "exists": True}}
    result = evaluate_condition_with_trace(condition, {"actor": {}})

    assert result.matched is True
    assert result.missing_fields == {"actor.department"}


def test_dsl_handles_type_mismatch_as_non_match_without_crash() -> None:
    condition = {"field": "amount", "gt": 100}
    result = evaluate_condition_with_trace(condition, {"amount": "150"})

    assert result.matched is False
    assert result.missing_fields == set()


def test_conflicting_block_and_allow_rules_resolve_to_block_and_flag_conflict() -> None:
    evaluator = PolicyEvaluator(
        rules=[
            _rule("allow_small", condition={"field": "amount", "lte": 1000}),
            _rule(
                "block_any_external",
                condition={"field": "payment_channel", "eq": "external"},
                decision=RuleDecision.BLOCK,
            ),
        ],
        policy_bundle=PolicyBundleMetadata(
            bundle_name="test-bundle",
            version="1",
            loaded_from="tests",
            context_schema={"amount": "int", "payment_channel": "str"},
        ),
    )

    trace = evaluator.evaluate(
        ActionProposal(
            action_type="approve_vendor_payment",
            actor_id="u-1",
            actor_role="finance_analyst",
            attributes={"amount": 300, "payment_channel": "external"},
        ),
        {},
    )

    assert trace.outcome == DecisionOutcome.BLOCKED
    assert trace.conflicting_rules == ["block_any_external"]
    assert "conflicting rules" in trace.reasoning.precedence_explanation.lower()


def test_strict_allow_mode_blocks_when_only_escalation_matches() -> None:
    evaluator = PolicyEvaluator(
        rules=[
            _rule(
                "escalate_high_amount",
                condition={"field": "amount", "gt": 5000},
                decision=RuleDecision.ESCALATE,
            )
        ],
        config=EvaluatorConfig(require_allow_match=True),
    )

    trace = evaluator.evaluate(
        ActionProposal(
            action_type="approve_vendor_payment",
            actor_id="u-1",
            actor_role="finance_analyst",
            attributes={"amount": 8000},
        ),
        {},
    )

    assert trace.outcome == DecisionOutcome.BLOCKED
    assert "strict allow mode" in trace.reasoning.precedence_explanation.lower()


def test_strict_mode_identity_block_happens_before_rule_evaluation() -> None:
    evaluator = PolicyEvaluator(
        rules=[
            _rule("allow_verified", condition={"field": "vendor_verified", "eq": True})
        ],
        config=EvaluatorConfig(require_allow_match=True),
    )

    trace = evaluator.evaluate(
        ActionProposal(
            action_type="approve_vendor_payment",
            attributes={"vendor_verified": True},
        ),
        {},
    )

    assert trace.outcome == DecisionOutcome.BLOCKED
    assert trace.matched_rules == []
    assert trace.missing_fields == ["actor_id", "actor_role"]
    assert "strict allow mode" in trace.reasoning.precedence_explanation.lower()
