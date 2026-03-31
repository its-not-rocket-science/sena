from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sena.policy.builtins import ALLOWED_OPERATORS

MISSING = object()


@dataclass
class ConditionEvaluation:
    matched: bool
    missing_fields: set[str] = field(default_factory=set)


def resolve_field(field: str, context: dict[str, Any]) -> Any:
    value: Any = context
    for part in field.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return MISSING
    return value


def evaluate_condition(condition: dict[str, Any], context: dict[str, Any]) -> bool:
    return evaluate_condition_with_trace(condition, context).matched


def evaluate_condition_with_trace(
    condition: dict[str, Any], context: dict[str, Any]
) -> ConditionEvaluation:
    if "and" in condition:
        child_results = [evaluate_condition_with_trace(item, context) for item in condition["and"]]
        missing_fields = {field for result in child_results for field in result.missing_fields}
        return ConditionEvaluation(
            matched=all(result.matched for result in child_results),
            missing_fields=missing_fields,
        )
    if "or" in condition:
        child_results = [evaluate_condition_with_trace(item, context) for item in condition["or"]]
        missing_fields = {field for result in child_results for field in result.missing_fields}
        return ConditionEvaluation(
            matched=any(result.matched for result in child_results),
            missing_fields=missing_fields,
        )
    if "not" in condition:
        result = evaluate_condition_with_trace(condition["not"], context)
        return ConditionEvaluation(matched=not result.matched, missing_fields=result.missing_fields)

    field = condition["field"]
    left = resolve_field(field, context)
    missing_fields = {field} if left is MISSING else set()

    for op_name, op in ALLOWED_OPERATORS.items():
        if op_name in condition:
            right = condition[op_name]
            try:
                return ConditionEvaluation(
                    matched=False if left is MISSING else bool(op(left, right)),
                    missing_fields=missing_fields,
                )
            except TypeError:
                return ConditionEvaluation(matched=False, missing_fields=missing_fields)
    return ConditionEvaluation(matched=False, missing_fields=missing_fields)
