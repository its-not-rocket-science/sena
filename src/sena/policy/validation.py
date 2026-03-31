from __future__ import annotations

from typing import Any

from sena.policy.grammar import COMPARISON_OPERATORS, LOGICAL_OPERATORS


class PolicyValidationError(ValueError):
    pass


def validate_condition(node: Any) -> None:
    if not isinstance(node, dict):
        raise PolicyValidationError("condition nodes must be dictionaries")

    unknown_keys = [
        key
        for key in node
        if key not in LOGICAL_OPERATORS and key not in COMPARISON_OPERATORS and key != "field"
    ]
    if unknown_keys:
        raise PolicyValidationError(f"unsupported operator(s) in condition: {unknown_keys}")

    if any(op in node for op in LOGICAL_OPERATORS):
        keys = [k for k in node if k in LOGICAL_OPERATORS]
        if len(keys) != 1:
            raise PolicyValidationError("condition must contain exactly one logical operator")
        op = keys[0]
        payload = node[op]
        if op in {"and", "or"}:
            if not isinstance(payload, list) or not payload:
                raise PolicyValidationError(f"'{op}' must be a non-empty list")
            for child in payload:
                validate_condition(child)
            return
        if op == "not":
            validate_condition(payload)
            return

    if "field" not in node or not isinstance(node["field"], str):
        raise PolicyValidationError("leaf condition must include string 'field'")

    ops = [k for k in node if k in COMPARISON_OPERATORS]
    if len(ops) != 1:
        raise PolicyValidationError("leaf condition must include exactly one comparison operator")


def validate_rule_payload(rule: dict[str, Any]) -> None:
    required = {
        "id",
        "description",
        "severity",
        "inviolable",
        "applies_to",
        "condition",
        "decision",
        "reason",
    }
    missing = required - set(rule.keys())
    if missing:
        raise PolicyValidationError(f"rule missing required fields: {sorted(missing)}")

    if not isinstance(rule["applies_to"], list) or not rule["applies_to"]:
        raise PolicyValidationError("'applies_to' must be a non-empty list")

    validate_condition(rule["condition"])
