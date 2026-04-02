from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sena.core.models import (
    ActionProposal,
    EvaluatorConfig,
    PolicyBundleMetadata,
    PolicyRule,
)
from sena.engine.evaluator import PolicyEvaluator


@dataclass(frozen=True)
class SimulationScenario:
    action_type: str
    request_id: str | None
    actor_id: str | None
    attributes: dict[str, Any]
    facts: dict[str, Any]
    source_system: str | None = None
    workflow_stage: str | None = None
    risk_category: str | None = None


@dataclass(frozen=True)
class SimulationChange:
    scenario_id: str
    source_system: str
    workflow_stage: str
    risk_category: str
    before_outcome: str
    after_outcome: str
    changed: bool
    before_summary: str
    after_summary: str
    before_matched_rules: list[str]
    after_matched_rules: list[str]


def _group_key(change: SimulationChange, field: str) -> str:
    return str(getattr(change, field)).strip() or "unknown"


def simulate_bundle_impact(
    scenarios: dict[str, SimulationScenario],
    from_rules: list[PolicyRule],
    to_rules: list[PolicyRule],
    from_bundle: PolicyBundleMetadata,
    to_bundle: PolicyBundleMetadata,
    config: EvaluatorConfig | None = None,
) -> dict[str, Any]:
    cfg = config or EvaluatorConfig()
    from_eval = PolicyEvaluator(from_rules, policy_bundle=from_bundle, config=cfg)
    to_eval = PolicyEvaluator(to_rules, policy_bundle=to_bundle, config=cfg)

    changes: list[SimulationChange] = []
    for scenario_id, scenario in sorted(scenarios.items()):
        proposal = ActionProposal(
            action_type=scenario.action_type,
            request_id=scenario.request_id,
            actor_id=scenario.actor_id,
            attributes=scenario.attributes,
        )
        before = from_eval.evaluate(proposal, scenario.facts)
        after = to_eval.evaluate(proposal, scenario.facts)
        source_system = (
            scenario.source_system
            or str(scenario.attributes.get("source_system") or "").strip()
            or "unknown"
        )
        workflow_stage = (
            scenario.workflow_stage
            or str(scenario.attributes.get("workflow_stage") or "").strip()
            or "unknown"
        )
        risk_category = (
            scenario.risk_category
            or str(scenario.attributes.get("risk_category") or "").strip()
            or "general"
        )
        changes.append(
            SimulationChange(
                scenario_id=scenario_id,
                source_system=source_system,
                workflow_stage=workflow_stage,
                risk_category=risk_category,
                before_outcome=before.outcome.value,
                after_outcome=after.outcome.value,
                changed=before.outcome != after.outcome,
                before_summary=before.summary,
                after_summary=after.summary,
                before_matched_rules=[rule.rule_id for rule in before.matched_rules],
                after_matched_rules=[rule.rule_id for rule in after.matched_rules],
            )
        )

    changed = [c for c in changes if c.changed]
    grouped: dict[str, dict[str, Any]] = {}
    for field in ("source_system", "workflow_stage", "risk_category"):
        bucket: dict[str, Any] = {}
        for change in changes:
            key = _group_key(change, field)
            data = bucket.setdefault(
                key, {"total": 0, "changed": 0, "changed_scenarios": []}
            )
            data["total"] += 1
            if change.changed:
                data["changed"] += 1
                data["changed_scenarios"].append(change.scenario_id)
        grouped[field] = bucket
    return {
        "total_scenarios": len(changes),
        "changed_scenarios": len(changed),
        "change_ratio": 0.0 if not changes else len(changed) / len(changes),
        "grouped_changes": grouped,
        "changes": [c.__dict__ for c in changes],
    }
