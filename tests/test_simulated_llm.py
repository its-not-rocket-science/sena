from sena.llm.simulated_adapter import SimulatedLLMAdapter


def test_extract_facts_basic_keywords() -> None:
    llm = SimulatedLLMAdapter(seed=42)

    facts = llm.extract_facts(
        "Please open the airlock, there is danger and the crew is outside.",
        {
            "action_requested": str,
            "human_safety_risk": bool,
            "crew_in_airlock": bool,
        },
    )

    assert facts["action_requested"] == "open"
    assert facts["human_safety_risk"] is True
    assert isinstance(facts["crew_in_airlock"], bool)


def test_generate_rules_count() -> None:
    llm = SimulatedLLMAdapter(seed=42)
    rules = llm.generate_rules("robotics safety", 4)
    assert len(rules) == 4


def test_format_output_for_blocked_case() -> None:
    llm = SimulatedLLMAdapter(seed=42)
    output = llm.format_output(
        {"_blocked": True, "_block_reason": "Action blocked by safety constraints."},
        [],
    )
    assert "blocked" in output.lower()


def test_call_history_records_activity() -> None:
    llm = SimulatedLLMAdapter(seed=42)
    llm.generate_rules("robotics", 2)
    history = llm.get_call_history()
    assert len(history) == 1
    assert history[0]["method"] == "generate_rules"