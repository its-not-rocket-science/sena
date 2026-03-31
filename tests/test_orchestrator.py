from sena.core.types import Rule
from sena.evolutionary.deap_adapter import DEAPAdapter
from sena.llm.simulated_adapter import SimulatedLLMAdapter
from sena.orchestrator.sena import SENA
from sena.production_systems.experta_adapter import ExpertaAdapter


def build_sena() -> SENA:
    inviolable_rules = [
        Rule(
            condition="human_safety_risk == True OR action_would_harm_human == True",
            action="BLOCK:Action would violate First Law of Robotics",
            name="first_law",
            priority=100,
            inviolable=True,
        )
    ]

    return SENA(
        production_system=ExpertaAdapter(),
        evolutionary_algorithm=DEAPAdapter(population_size=6),
        llm=SimulatedLLMAdapter(seed=42),
        inviolable_rules=inviolable_rules,
    )


def test_initialise_from_domain_creates_population() -> None:
    sena = build_sena()
    sena.initialise_from_domain("robotics control", num_initial_rules=6)
    assert len(sena.ea.get_population()) == 6


def test_training_produces_history() -> None:
    sena = build_sena()
    sena.initialise_from_domain("robotics control", num_initial_rules=6)

    history = sena.train(
        test_scenarios=[
            {
                "name": "safe_case",
                "initial_memory": {
                    "human_safety_risk": False,
                    "action_would_harm_human": False,
                },
                "expected_output_contains": [],
            }
        ],
        generations=2,
        use_llm_mutation=False,
    )

    assert len(history) == 2


def test_evaluate_blocks_unsafe_case_after_training() -> None:
    sena = build_sena()
    sena.initialise_from_domain("robotics control", num_initial_rules=6)
    sena.train(
        test_scenarios=[
            {
                "name": "unsafe_case",
                "initial_memory": {
                    "human_safety_risk": True,
                    "action_would_harm_human": True,
                },
                "expected_output_contains": [],
                "expects_block": True,
            }
        ],
        generations=1,
        use_llm_mutation=False,
    )

    result = sena.evaluate(
        {
            "human_safety_risk": True,
            "action_would_harm_human": True,
        }
    )

    assert result["blocked"] is True
    assert "first law" in result["output"].lower() or "violate" in result["output"].lower()


def test_explain_decision_returns_text() -> None:
    sena = build_sena()
    sena.initialise_from_domain("robotics control", num_initial_rules=6)
    sena.train(
        test_scenarios=[
            {
                "name": "unsafe_case",
                "initial_memory": {
                    "human_safety_risk": True,
                    "action_would_harm_human": True,
                },
                "expected_output_contains": [],
                "expects_block": True,
            }
        ],
        generations=1,
        use_llm_mutation=False,
    )

    explanation = sena.explain_decision(
        {
            "human_safety_risk": True,
            "action_would_harm_human": True,
        }
    )

    assert "SENA Decision Explanation" in explanation
    assert "Rule:" in explanation