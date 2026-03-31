from sena.core.enums import DecisionOutcome


def test_decision_outcome_enum() -> None:
    assert DecisionOutcome.BLOCKED.value == "BLOCKED"
