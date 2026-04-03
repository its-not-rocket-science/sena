import json

from sena.core.models import PolicyBundleMetadata
from sena.engine.simulation import SimulationScenario, simulate_bundle_impact
from sena.policy.lifecycle import (
    PromotionGatePolicy,
    diff_rule_sets,
    evaluate_promotion_gate,
    validate_lifecycle_transition,
    validate_promotion,
)
from sena.policy.parser import load_policy_bundle


def test_diff_and_promotion_validation(tmp_path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()

    source.joinpath("bundle.yaml").write_text(
        "bundle_name: source\nversion: 1\nlifecycle: draft\n"
    )
    target.joinpath("bundle.yaml").write_text(
        "bundle_name: target\nversion: 2\nlifecycle: candidate\n"
    )

    source.joinpath("policy.yaml").write_text(
        """
- id: allow_small
  description: allow small amounts
  severity: low
  inviolable: false
  applies_to: [approve_vendor_payment]
  condition: {field: amount, lt: 1000}
  decision: ALLOW
  reason: small amount
""".strip()
    )
    target.joinpath("policy.yaml").write_text(
        """
- id: allow_small
  description: allow small amounts changed
  severity: low
  inviolable: false
  applies_to: [approve_vendor_payment]
  condition: {field: amount, lt: 1000}
  decision: ALLOW
  reason: small amount
- id: block_large
  description: block large amounts
  severity: high
  inviolable: true
  applies_to: [approve_vendor_payment]
  condition: {field: amount, gte: 1000}
  decision: BLOCK
  reason: too large
""".strip()
    )

    source_rules, source_meta = load_policy_bundle(source)
    target_rules, target_meta = load_policy_bundle(target)
    diff = diff_rule_sets(source_rules, target_rules)

    assert diff.added_rule_ids == ["block_large"]
    assert diff.changed_rule_ids == ["allow_small"]

    promotion = validate_promotion(
        source_meta.lifecycle, target_meta.lifecycle, source_rules, target_rules
    )
    assert promotion.valid is True


def test_lifecycle_transition_disallows_skip_and_backwards() -> None:
    assert validate_lifecycle_transition("draft", "active").valid is False
    assert validate_lifecycle_transition("active", "candidate").valid is False
    assert validate_lifecycle_transition("draft", "candidate").valid is True


def test_simulation_impact_changes_are_reported() -> None:
    rules_a, meta_a = load_policy_bundle("src/sena/examples/policies")
    meta_a = PolicyBundleMetadata(**{**meta_a.__dict__, "version": "A"})
    meta_b = PolicyBundleMetadata(**{**meta_a.__dict__, "version": "B"})

    scenarios = {
        "small": SimulationScenario(
            action_type="approve_vendor_payment",
            request_id="r-small",
            actor_id="u-1",
            source_system="jira",
            workflow_stage="pending_approval",
            risk_category="vendor_payment",
            attributes={"amount": 10, "vendor_verified": True, "source_system": "jira"},
            facts={},
        ),
        "large": SimulationScenario(
            action_type="approve_vendor_payment",
            request_id="r-large",
            actor_id="u-2",
            source_system="servicenow",
            workflow_stage="requested",
            risk_category="change_governance",
            attributes={
                "amount": 90000,
                "vendor_verified": False,
                "source_system": "servicenow",
            },
            facts={},
        ),
    }

    report = simulate_bundle_impact(scenarios, rules_a, rules_a, meta_a, meta_b)
    assert report["total_scenarios"] == 2
    assert report["changed_scenarios"] == 0
    assert report["grouped_changes"]["source_system"]["jira"]["total"] == 1
    assert report["grouped_changes"]["source_system"]["servicenow"]["total"] == 1
    assert json.dumps(report)


def test_promotion_gate_rejects_malformed_simulation_report() -> None:
    failures = evaluate_promotion_gate(
        target_lifecycle="active",
        validation_artifact="CAB-1",
        simulation_report={
            "total_scenarios": 2,
            "changed_scenarios": 1,
            "changes": [{"scenario_id": "s-1", "before_outcome": "APPROVED"}],
        },
        break_glass=False,
        break_glass_reason=None,
        policy=PromotionGatePolicy(),
    )
    assert failures
    assert any(item.code == "invalid_simulation_report" for item in failures)
