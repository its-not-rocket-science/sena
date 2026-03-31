import pytest

from sena.core.enums import RuleDecision, Severity
from sena.core.models import PolicyRule
from sena.policy.validation import PolicyValidationError, validate_condition, validate_rule_payload
from sena.policy.validation import validate_policy_coverage


def test_invalid_condition_without_field() -> None:
    with pytest.raises(PolicyValidationError):
        validate_condition({"eq": 1})


def test_unsupported_operator_rejected() -> None:
    with pytest.raises(PolicyValidationError, match="unsupported operator"):
        validate_condition({"field": "amount", "approx": 2})


def test_nested_logical_expression_is_valid() -> None:
    validate_condition(
        {
            "and": [
                {"field": "amount", "gte": 100},
                {"or": [{"field": "risk_score", "gte": 80}, {"not": {"field": "vip", "eq": True}}]},
            ]
        }
    )


def test_missing_required_rule_fields_rejected() -> None:
    with pytest.raises(PolicyValidationError, match="missing required fields"):
        validate_rule_payload({"id": "rule-1", "condition": {"field": "x", "eq": 1}})


def test_policy_coverage_detects_missing_action_type() -> None:
    rules = [
        PolicyRule(
            id="r1",
            description="test",
            severity=Severity.LOW,
            inviolable=False,
            applies_to=["approve_vendor_payment"],
            condition={"field": "amount", "gte": 1},
            decision=RuleDecision.ALLOW,
            reason="ok",
        )
    ]

    missing = validate_policy_coverage(
        rules,
        required_action_types=["approve_vendor_payment", "issue_refund"],
    )
    assert missing == ["issue_refund"]
