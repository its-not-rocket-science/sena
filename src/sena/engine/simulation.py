from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sena.core.models import ActionProposal, EvaluatorConfig, PolicyBundleMetadata, PolicyRule
from sena.engine.evaluator import PolicyEvaluator


@dataclass(frozen=True)
class SimulationScenario:
    action_type: str
    request_id: str | None
    actor_id: str | None
    attributes: dict[str, Any]
    facts: dict[str, Any]


@dataclass(frozen=True)
class SimulationChange:
    scenario_id: str
    before_outcome: str
    after_outcome: str
    changed: bool


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
        changes.append(
            SimulationChange(
                scenario_id=scenario_id,
                before_outcome=before.outcome.value,
                after_outcome=after.outcome.value,
                changed=before.outcome != after.outcome,
            )
        )

    changed = [c for c in changes if c.changed]
    return {
        "total_scenarios": len(changes),
        "changed_scenarios": len(changed),
        "change_ratio": 0.0 if not changes else len(changed) / len(changes),
        "changes": [c.__dict__ for c in changes],
    }
