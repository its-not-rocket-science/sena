from __future__ import annotations

import json
from dataclasses import dataclass

from sena.core.enums import RuleDecision
from sena.core.models import PolicyRule


ALLOWED_LIFECYCLE_TRANSITIONS = {
    ("draft", "candidate"),
    ("candidate", "active"),
    ("active", "deprecated"),
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
    if (source_lifecycle, target_lifecycle) in ALLOWED_LIFECYCLE_TRANSITIONS:
        return PromotionValidation(valid=True, errors=[])
    return PromotionValidation(
        valid=False,
        errors=[f"invalid lifecycle transition '{source_lifecycle}' -> '{target_lifecycle}'"],
    )


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
    *,
    validation_artifact: str | None = None,
) -> PromotionValidation:
    transition = validate_lifecycle_transition(source_lifecycle, target_lifecycle)
    errors: list[str] = list(transition.errors)

    diff = diff_rule_sets(source_rules, target_rules)
    if target_lifecycle == "active" and not validation_artifact:
        errors.append("promotion to active requires validation artifact")
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
