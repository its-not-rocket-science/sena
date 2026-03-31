from sena.core.types import Rule
from sena.production_systems.experta_adapter import ExpertaAdapter


def test_add_and_get_rules() -> None:
    ps = ExpertaAdapter()
    rule = Rule(condition="True", action="SET:ok=true")
    ps.add_rule(rule)

    rules = ps.get_rules()
    assert len(rules) == 1
    assert rules[0].action == "SET:ok=true"


def test_inviolable_rule_is_preserved() -> None:
    ps = ExpertaAdapter()
    safe_rule = Rule(condition="risk_level > 0.8", action="BLOCK:too risky")
    ps.add_rule(safe_rule, inviolable=True)

    assert len(ps.get_inviolable_rules()) == 1
    assert ps.remove_rule(safe_rule.rule_id) is False


def test_inference_blocks_on_inviolable_rule() -> None:
    ps = ExpertaAdapter()
    ps.add_rule(
        Rule(
            condition="human_safety_risk == True",
            action="BLOCK:First Law violation",
            name="first_law",
        ),
        inviolable=True,
    )
    ps.add_rule(
        Rule(
            condition="True",
            action="OUTPUT:This should not execute",
            name="normal_rule",
        )
    )

    memory, trace = ps.infer({"human_safety_risk": True})

    assert memory["_blocked"] is True
    assert "First Law violation" in memory["_block_reason"]
    assert len(trace) == 1
    assert trace[0].rule_name == "first_law"


def test_clear_rules_preserves_inviolable_by_default() -> None:
    ps = ExpertaAdapter()
    ps.add_rule(Rule(condition="True", action="BLOCK:stop"), inviolable=True)
    ps.add_rule(Rule(condition="True", action="SET:x=1"), inviolable=False)

    ps.clear_rules()

    assert len(ps.get_rules()) == 1
    assert len(ps.get_inviolable_rules()) == 1