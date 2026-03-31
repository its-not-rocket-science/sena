from __future__ import annotations

from typing import Any

from sena.policy.builtins import ALLOWED_OPERATORS


def resolve_field(field: str, context: dict[str, Any]) -> Any:
    value: Any = context
    for part in field.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return None
    return value


def evaluate_condition(condition: dict[str, Any], context: dict[str, Any]) -> bool:
    if "and" in condition:
        return all(evaluate_condition(item, context) for item in condition["and"])
    if "or" in condition:
        return any(evaluate_condition(item, context) for item in condition["or"])
    if "not" in condition:
        return not evaluate_condition(condition["not"], context)

    field = condition["field"]
    left = resolve_field(field, context)

    for op_name, op in ALLOWED_OPERATORS.items():
        if op_name in condition:
            right = condition[op_name]
            try:
                return bool(op(left, right))
            except TypeError:
                return False
    return False
