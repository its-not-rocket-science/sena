import pytest

from sena.policy.validation import PolicyValidationError, validate_condition, validate_rule_payload


def test_invalid_condition_without_field() -> None:
    with pytest.raises(PolicyValidationError):
        validate_condition({"eq": 1})


def test_unsupported_operator_rejected() -> None:
    with pytest.raises(PolicyValidationError, match="unsupported operator"):
        validate_condition({"field": "amount", "between": [1, 2]})


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
