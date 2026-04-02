from sena.policy.interpreter import evaluate_condition_with_trace


def test_missing_field_tracking_distinguishes_none_from_missing() -> None:
    condition = {"field": "actor.department", "eq": None}

    present_none = evaluate_condition_with_trace(
        condition, {"actor": {"department": None}}
    )
    missing_field = evaluate_condition_with_trace(condition, {"actor": {}})

    assert present_none.matched is True
    assert present_none.missing_fields == set()
    assert missing_field.missing_fields == {"actor.department"}
