from sena.core.types import Genome, Rule


def test_rule_evaluate_true() -> None:
    rule = Rule(condition="risk_level > 0.5", action="BLOCK:too risky")
    assert rule.evaluate({"risk_level": 0.9}) is True


def test_rule_evaluate_false() -> None:
    rule = Rule(condition="risk_level > 0.5", action="BLOCK:too risky")
    assert rule.evaluate({"risk_level": 0.1}) is False


def test_rule_execute_set() -> None:
    rule = Rule(condition="True", action='SET:priority="high"')
    memory = rule.execute({})
    assert memory["priority"] == "high"


def test_rule_execute_output() -> None:
    rule = Rule(condition="True", action="OUTPUT:Hello world")
    memory = rule.execute({})
    assert memory["_last_output"] == "Hello world"


def test_rule_execute_block() -> None:
    rule = Rule(condition="True", action="BLOCK:Unsafe action")
    memory = rule.execute({})
    assert memory["_blocked"] is True
    assert memory["_block_reason"] == "Unsafe action"


def test_rule_serialisation_roundtrip() -> None:
    rule = Rule(
        condition="x > 1",
        action="SET:y=2",
        name="sample_rule",
        priority=10,
        inviolable=True,
    )
    restored = Rule.from_dict(rule.to_dict())
    assert restored.condition == rule.condition
    assert restored.action == rule.action
    assert restored.name == rule.name
    assert restored.priority == rule.priority
    assert restored.inviolable == rule.inviolable


def test_genome_rule_filters() -> None:
    rules = [
        Rule(condition="True", action="SET:a=1", inviolable=True),
        Rule(condition="True", action="SET:b=2", inviolable=False),
    ]
    genome = Genome(rules=rules)

    assert len(genome.get_inviolable_rules()) == 1
    assert len(genome.get_evolvable_rules()) == 1