from __future__ import annotations

import json
from dataclasses import dataclass, field

from sena.core.enums import RuleDecision
from sena.core.models import PolicyRule

ALLOWED_LIFECYCLE_TRANSITIONS = {
    ("draft", "candidate"),
    ("candidate", "approved"),
    ("candidate", "active"),
    ("approved", "active"),
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

@dataclass(frozen=True)
class PromotionFailure:
    code: str
    message: str
    details: dict[str, object] = field(default_factory=dict)

@dataclass(frozen=True)
class PromotionGatePolicy:
    require_validation_artifact: bool = True
    require_simulation: bool = True
    required_scenario_ids: tuple[str, ...] = ()
    max_changed_outcomes: int | None = None
    max_regressions_by_outcome_type: dict[str, int] = field(default_factory=dict)
    break_glass_enabled: bool = True

def _parse_non_negative_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if not isinstance(value, int):
        return None
    if value < 0:
        return None
    return value

def validate_simulation_report(simulation_report: dict[str, object]) -> list[PromotionFailure]:
    failures: list[PromotionFailure] = []
    total_scenarios = _parse_non_negative_int(simulation_report.get("total_scenarios"))
    changed_scenarios = _parse_non_negative_int(
        simulation_report.get("changed_scenarios")
    )
    changes = simulation_report.get("changes")

    if total_scenarios is None:
        failures.append(
            PromotionFailure(
                code="invalid_simulation_report",
                message="simulation report must include non-negative integer total_scenarios",
            )
        )
    if changed_scenarios is None:
        failures.append(
            PromotionFailure(
                code="invalid_simulation_report",
                message="simulation report must include non-negative integer changed_scenarios",
            )
        )
    if not isinstance(changes, list):
        failures.append(
            PromotionFailure(
                code="invalid_simulation_report",
                message="simulation report must include changes as a list",
            )
        )
        return failures
    if not changes:
        failures.append(
            PromotionFailure(
                code="invalid_simulation_report",
                message="simulation report must include at least one scenario change entry",
            )
        )
        return failures

    scenario_ids: set[str] = set()
    for index, item in enumerate(changes, start=1):
        if not isinstance(item, dict):
            failures.append(
                PromotionFailure(
                    code="invalid_simulation_report",
                    message=f"simulation changes[{index}] must be an object",
                )
            )
            continue
        scenario_id = str(item.get("scenario_id") or "").strip()
        before_outcome = str(item.get("before_outcome") or "").strip()
        after_outcome = str(item.get("after_outcome") or "").strip()
        if not scenario_id:
            failures.append(
                PromotionFailure(
                    code="invalid_simulation_report",
                    message=f"simulation changes[{index}] is missing scenario_id",
                )
            )
            continue
        if scenario_id in scenario_ids:
            failures.append(
                PromotionFailure(
                    code="invalid_simulation_report",
                    message=f"simulation report contains duplicate scenario_id '{scenario_id}'",
                )
            )
        scenario_ids.add(scenario_id)
        if not before_outcome or not after_outcome:
            failures.append(
                PromotionFailure(
                    code="invalid_simulation_report",
                    message=f"simulation changes[{index}] must include before_outcome and after_outcome",
                )
            )

    if (
        total_scenarios is not None
        and total_scenarios > 0
        and len(scenario_ids) != total_scenarios
    ):
        failures.append(
            PromotionFailure(
                code="invalid_simulation_report",
                message="simulation report total_scenarios does not match unique scenario entries",
                details={
                    "total_scenarios": total_scenarios,
                    "unique_scenarios": len(scenario_ids),
                },
            )
        )
    if (
        total_scenarios is not None
        and changed_scenarios is not None
        and changed_scenarios > total_scenarios
    ):
        failures.append(
            PromotionFailure(
                code="invalid_simulation_report",
                message="simulation report changed_scenarios exceeds total_scenarios",
                details={
                    "total_scenarios": total_scenarios,
                    "changed_scenarios": changed_scenarios,
                },
            )
        )
    return failures

def validate_lifecycle_transition(
    source_lifecycle: str, target_lifecycle: str
) -> PromotionValidation:
    if (source_lifecycle, target_lifecycle) in ALLOWED_LIFECYCLE_TRANSITIONS:
        return PromotionValidation(valid=True, errors=[])
    return PromotionValidation(
        valid=False,
        errors=[
            f"invalid lifecycle transition '{source_lifecycle}' -> '{target_lifecycle}'"
        ],
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
        if _rule_fingerprint(current_map[rule_id])
        != _rule_fingerprint(target_map[rule_id])
    )
    return BundleDiff(
        added_rule_ids=added, removed_rule_ids=removed, changed_rule_ids=changed
    )

def validate_promotion(
    source_lifecycle: str,
    target_lifecycle: str,
    source_rules: list[PolicyRule],
    target_rules: list[PolicyRule],
    *,
    validation_artifact: str | None = None,
    simulation_report: dict[str, object] | None = None,
    approver_attestations: list[str] | None = None,
    signature_verified: bool | None = None,
    signature_verification_strict: bool = False,
) -> PromotionValidation:
    transition = validate_lifecycle_transition(source_lifecycle, target_lifecycle)
    errors: list[str] = list(transition.errors)

    diff = diff_rule_sets(source_rules, target_rules)
    if target_lifecycle in {"approved", "active"} and not validation_artifact:
        errors.append("promotion to approved/active requires validation artifact")
    if target_lifecycle in {"approved", "active"} and not (
        diff.added_rule_ids or diff.changed_rule_ids
    ):
        errors.append(
            "promotion to approved/active requires at least one added or changed rule"
        )
    if source_lifecycle == "candidate" and target_lifecycle in {"approved", "active"}:
        if simulation_report is None:
            errors.append(
                "promotion from candidate requires simulation report"
            )
        attestations = sorted(
            {item.strip() for item in (approver_attestations or []) if item.strip()}
        )
        if len(attestations) < 2:
            errors.append(
                "promotion from candidate requires at least two approver attestations"
            )

    target_ids = {rule.id for rule in target_rules}
    if len(target_ids) != len(target_rules):
        errors.append("target bundle contains duplicate rule ids")

    if target_lifecycle == "active":
        blocking_rules = [
            rule for rule in target_rules if rule.decision == RuleDecision.BLOCK
        ]
        if not blocking_rules:
            errors.append("active bundle must include at least one BLOCK rule")
    if (
        target_lifecycle == "active"
        and signature_verification_strict
        and not signature_verified
    ):
        errors.append(
            "active promotion requires a valid signed release manifest in strict mode"
        )

    return PromotionValidation(valid=not errors, errors=errors)

def evaluate_promotion_gate(
    *,
    target_lifecycle: str,
    validation_artifact: str | None,
    simulation_report: dict[str, object] | None,
    break_glass: bool,
    break_glass_reason: str | None,
    policy: PromotionGatePolicy,
) -> list[PromotionFailure]:
    failures: list[PromotionFailure] = []
    if target_lifecycle != "active":
        return failures

    if break_glass:
        if not policy.break_glass_enabled:
            failures.append(
                PromotionFailure(
                    code="break_glass_disabled",
                    message="break-glass override is disabled by policy",
                )
            )
        if not (break_glass_reason or "").strip():
            failures.append(
                PromotionFailure(
                    code="break_glass_reason_required",
                    message="break_glass_reason is required when break_glass=true",
                )
            )
        return failures

    if policy.require_validation_artifact and not (validation_artifact or "").strip():
        failures.append(
            PromotionFailure(
                code="missing_validation_artifact",
                message="promotion to active requires validation artifact",
            )
        )
    if policy.require_simulation and simulation_report is None:
        failures.append(
            PromotionFailure(
                code="missing_simulation_report",
                message="promotion to active requires simulation report",
            )
        )
        return failures
    if simulation_report is None:
        return failures
    failures.extend(validate_simulation_report(simulation_report))
    if failures:
        return failures

    observed_ids = {
        str(item.get("scenario_id"))
        for item in simulation_report.get("changes", [])
        if isinstance(item, dict) and item.get("scenario_id")
    }
    missing_scenarios = sorted(set(policy.required_scenario_ids) - observed_ids)
    if missing_scenarios:
        failures.append(
            PromotionFailure(
                code="required_scenarios_missing",
                message="simulation report does not contain all required scenarios",
                details={"missing_scenario_ids": missing_scenarios},
            )
        )

    if policy.max_changed_outcomes is not None:
        changed = int(simulation_report.get("changed_scenarios", 0))
        if changed > policy.max_changed_outcomes:
            failures.append(
                PromotionFailure(
                    code="changed_outcome_budget_exceeded",
                    message="changed outcome budget exceeded",
                    details={
                        "observed": changed,
                        "max_allowed": policy.max_changed_outcomes,
                    },
                )
            )

    for transition, max_allowed in policy.max_regressions_by_outcome_type.items():
        before, _, after = transition.partition("->")
        if not before or not after:
            failures.append(
                PromotionFailure(
                    code="invalid_regression_budget_key",
                    message="regression budget key must use BEFORE->AFTER format",
                    details={"transition": transition},
                )
            )
            continue
        observed = sum(
            1
            for item in simulation_report.get("changes", [])
            if isinstance(item, dict)
            and item.get("before_outcome") == before
            and item.get("after_outcome") == after
            and item.get("before_outcome") != item.get("after_outcome")
        )
        if observed > max_allowed:
            failures.append(
                PromotionFailure(
                    code="regression_budget_exceeded",
                    message=f"regression budget exceeded for {transition}",
                    details={
                        "transition": transition,
                        "observed": observed,
                        "max_allowed": max_allowed,
                    },
                )
            )
    return failures
