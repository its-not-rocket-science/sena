from __future__ import annotations

import json
from dataclasses import dataclass

from sena.core.enums import RuleDecision
from sena.core.models import PolicyRule


LIFECYCLE_ORDER = {
    "draft": 0,
    "candidate": 1,
    "active": 2,
    "deprecated": 3,
}


@dataclass(frozen=True)
class BundleDiff:
    added_rule_ids: list[str]
    removed_rule_ids: list[str]
    changed_rule_ids: list[str]


@dataclass(frozen=True)
class PromotionValidation:
    valid: bool
    errors: list[str]


def validate_lifecycle_transition(source_lifecycle: str, target_lifecycle: str) -> PromotionValidation:
    errors: list[str] = []

    if source_lifecycle not in LIFECYCLE_ORDER:
        errors.append(f"unsupported source lifecycle '{source_lifecycle}'")
    if target_lifecycle not in LIFECYCLE_ORDER:
        errors.append(f"unsupported target lifecycle '{target_lifecycle}'")

    if errors:
        return PromotionValidation(valid=False, errors=errors)

    if source_lifecycle == target_lifecycle:
        errors.append("lifecycle transition requires a new target state")
    elif LIFECYCLE_ORDER[target_lifecycle] < LIFECYCLE_ORDER[source_lifecycle]:
        errors.append("lifecycle cannot move backwards")
    elif LIFECYCLE_ORDER[target_lifecycle] - LIFECYCLE_ORDER[source_lifecycle] > 1:
        errors.append("lifecycle cannot skip states")

    return PromotionValidation(valid=not errors, errors=errors)


def _rule_fingerprint(rule: PolicyRule) -> tuple:
    return (
        rule.description,
        rule.severity.value,
        rule.inviolable,
        tuple(rule.applies_to),
        json.dumps(rule.condition, sort_keys=True, separators=(",", ":")),
        rule.decision.value,
        rule.reason,
    )


def diff_rule_sets(current: list[PolicyRule], target: list[PolicyRule]) -> BundleDiff:
    current_map = {rule.id: rule for rule in current}
    target_map = {rule.id: rule for rule in target}

    added = sorted(set(target_map) - set(current_map))
    removed = sorted(set(current_map) - set(target_map))
    changed = sorted(
        rule_id
        for rule_id in set(current_map).intersection(target_map)
        if _rule_fingerprint(current_map[rule_id]) != _rule_fingerprint(target_map[rule_id])
    )
    return BundleDiff(added_rule_ids=added, removed_rule_ids=removed, changed_rule_ids=changed)


def validate_promotion(
    source_lifecycle: str,
    target_lifecycle: str,
    source_rules: list[PolicyRule],
    target_rules: list[PolicyRule],
) -> PromotionValidation:
    transition = validate_lifecycle_transition(source_lifecycle, target_lifecycle)
    errors: list[str] = list(transition.errors)

    diff = diff_rule_sets(source_rules, target_rules)
    if target_lifecycle == "active" and not (diff.added_rule_ids or diff.changed_rule_ids):
        errors.append("promotion to active requires at least one added or changed rule")

    target_ids = {rule.id for rule in target_rules}
    if len(target_ids) != len(target_rules):
        errors.append("target bundle contains duplicate rule ids")

    if target_lifecycle == "active":
        blocking_rules = [rule for rule in target_rules if rule.decision == RuleDecision.BLOCK]
        if not blocking_rules:
            errors.append("active bundle must include at least one BLOCK rule")

    return PromotionValidation(valid=not errors, errors=errors)
