from __future__ import annotations

from typing import Any

from sena.core.enums import ActionOrigin, RuleDecision
from sena.core.models import ActionProposal
from sena.core.models import PolicyRule
from sena.policy.grammar import COMPARISON_OPERATORS, LOGICAL_OPERATORS

SUPPORTED_EVIDENCE_CLASSES = {
    "source_citations",
    "human_owner",
    "change_ticket",
    "simulation_preview",
    "rollback_plan",
    "model_provenance",
}


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
    op = ops[0]
    value = node[op]
    if op == "between":
        if not isinstance(value, list | tuple) or len(value) != 2:
            raise PolicyValidationError("'between' operator expects exactly two bounds")
    if op in {"starts_with", "ends_with", "matches_regex"} and not isinstance(value, str):
        raise PolicyValidationError(f"'{op}' operator expects a string value")
    if op == "exists" and not isinstance(value, bool):
        raise PolicyValidationError("'exists' operator expects true/false")


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

    required_evidence = rule.get("required_evidence", [])
    if required_evidence is None:
        required_evidence = []
    if not isinstance(required_evidence, list):
        raise PolicyValidationError("'required_evidence' must be a list when provided")
    unsupported = sorted(
        class_name for class_name in required_evidence if class_name not in SUPPORTED_EVIDENCE_CLASSES
    )
    if unsupported:
        raise PolicyValidationError(
            f"'required_evidence' includes unsupported class(es): {unsupported}"
        )

    missing_evidence_decision = rule.get("missing_evidence_decision")
    if missing_evidence_decision is not None and not required_evidence:
        raise PolicyValidationError(
            "'missing_evidence_decision' requires non-empty 'required_evidence'"
        )
    normalized_missing_evidence_decision = (
        missing_evidence_decision.value
        if isinstance(missing_evidence_decision, RuleDecision)
        else missing_evidence_decision
    )
    if normalized_missing_evidence_decision is not None and normalized_missing_evidence_decision not in {
        "BLOCK",
        "ESCALATE",
    }:
        raise PolicyValidationError(
            "'missing_evidence_decision' must be BLOCK or ESCALATE when provided"
        )


def validate_invariant_payload(invariant: dict[str, Any]) -> None:
    required = {
        "id",
        "description",
        "applies_to",
        "condition",
        "reason",
    }
    missing = required - set(invariant.keys())
    if missing:
        raise PolicyValidationError(f"invariant missing required fields: {sorted(missing)}")
    if not isinstance(invariant["applies_to"], list) or not invariant["applies_to"]:
        raise PolicyValidationError("invariant 'applies_to' must be a non-empty list")
    validate_condition(invariant["condition"])


def validate_policy_coverage(
    rules: list[PolicyRule],
    required_action_types: list[str],
    explicitly_allowed_action_types: list[str] | None = None,
    strict: bool = False,
) -> list[str]:
    explicitly_allowed = set(explicitly_allowed_action_types or [])
    covered_action_types = {action for rule in rules for action in rule.applies_to}

    missing = [
        action_type
        for action_type in required_action_types
        if action_type not in covered_action_types and action_type not in explicitly_allowed
    ]
    if missing and strict:
        raise PolicyValidationError(
            f"missing policy coverage for required action_type(s): {sorted(missing)}"
        )
    return missing


def _resolve_field(field: str, context: dict[str, Any]) -> Any:
    value: Any = context
    for part in field.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return None
    return value


def validate_context_schema(context: dict[str, Any], schema: dict[str, str]) -> list[str]:
    errors: list[str] = []
    expected = {"str": str, "int": int, "float": float, "bool": bool, "dict": dict, "list": list}
    for field, typename in schema.items():
        optional = typename.endswith("?")
        normalized_type = typename[:-1] if optional else typename
        value = _resolve_field(field, context)
        if value is None:
            if not optional:
                errors.append(f"missing required field '{field}'")
            continue
        py_type = expected.get(normalized_type)
        if py_type is None:
            errors.append(f"unsupported schema type '{typename}' for field '{field}'")
            continue
        if not isinstance(value, py_type):
            errors.append(
                f"field '{field}' expected type '{typename}' but received '{type(value).__name__}'"
            )
    return errors


def validate_identity_fields(actor_id: str | None, actor_role: str | None) -> list[str]:
    missing: list[str] = []
    if not actor_id:
        missing.append("actor_id")
    if not actor_role:
        missing.append("actor_role")
    return missing


def validate_ai_originated_action_fields(proposal: ActionProposal) -> list[str]:
    if proposal.action_origin != ActionOrigin.AI_SUGGESTED:
        return []

    missing: list[str] = []
    metadata = proposal.ai_metadata
    if metadata is None:
        return [
            "ai_metadata",
            "ai_metadata.originating_system",
            "ai_metadata.prompt_context_ref",
            "ai_metadata.requested_action",
            "ai_metadata.evidence_references",
            "ai_metadata.human_requester",
            "ai_metadata.human_owner",
            "ai_metadata.risk_classification",
        ]
    if not metadata.originating_system:
        missing.append("ai_metadata.originating_system")
    if not metadata.prompt_context_ref:
        missing.append("ai_metadata.prompt_context_ref")
    if not metadata.requested_action:
        missing.append("ai_metadata.requested_action")
    if not metadata.evidence_references:
        missing.append("ai_metadata.evidence_references")
    if not metadata.human_requester:
        missing.append("ai_metadata.human_requester")
    if not metadata.human_owner:
        missing.append("ai_metadata.human_owner")
    if metadata.risk_classification is None:
        missing.append("ai_metadata.risk_classification")
    else:
        if not metadata.risk_classification.category:
            missing.append("ai_metadata.risk_classification.category")
        if not metadata.risk_classification.level:
            missing.append("ai_metadata.risk_classification.level")
    return missing
