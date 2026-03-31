import pytest

from sena.policy.validation import PolicyValidationError, validate_condition


def test_invalid_condition_without_field() -> None:
    with pytest.raises(PolicyValidationError):
        validate_condition({"eq": 1})
