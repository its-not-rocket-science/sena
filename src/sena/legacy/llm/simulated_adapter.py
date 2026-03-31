"""Legacy research-prototype module (deprecated).

This module is preserved for historical context and backward compatibility only.
It is not part of the supported enterprise compliance engine.
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import Any, Dict, List

from sena.legacy.core.types import Rule, Trace


class SimulatedLLMAdapter:
    def __init__(self, seed: int = 42) -> None:
        self._random = random.Random(seed)
        self._call_history: List[Dict[str, Any]] = []

    def extract_facts(self, text: str, schema: Dict[str, type]) -> Dict[str, Any]:
        self._call_history.append(
            {
                "method": "extract_facts",
                "text": text,
                "timestamp": datetime.now().isoformat(),
            }
        )

        text_lower = text.lower()
        facts: Dict[str, Any] = {}

        for key in schema:
            if key == "action_requested":
                if "open" in text_lower:
                    facts[key] = "open"
                elif "cancel" in text_lower:
                    facts[key] = "cancel"
                elif "refund" in text_lower:
                    facts[key] = "refund"
                else:
                    facts[key] = None
            elif key == "human_safety_risk":
                facts[key] = any(word in text_lower for word in ["danger", "risk", "harm", "injury"])
            elif key == "crew_in_airlock":
                facts[key] = "crew" in text_lower and "airlock" in text_lower
            else:
                facts[key] = None

        return facts

    def generate_rules(
        self,
        description: str,
        num_rules: int,
    ) -> List[Rule]:
        self._call_history.append(
            {
                "method": "generate_rules",
                "description": description,
                "num_rules": num_rules,
                "timestamp": datetime.now().isoformat(),
            }
        )

        templates = [
            Rule(
                condition="action_requested == 'maintenance'",
                action="OUTPUT:Performing maintenance task.",
                name="maintenance_rule",
            ),
            Rule(
                condition="action_requested == 'move_arm'",
                action="OUTPUT:Moving arm safely.",
                name="move_arm_rule",
            ),
            Rule(
                condition="risk_level > 0.8",
                action="BLOCK:Risk level exceeds safety threshold",
                name="risk_rule",
            ),
            Rule(
                condition="crew_in_airlock == True and action_requested == 'open_airlock'",
                action="BLOCK:Cannot open airlock with crew inside",
                name="airlock_rule",
            ),
            Rule(
                condition="human_safety_risk == False",
                action="OUTPUT:Operation completed safely.",
                name="safe_operation_rule",
            ),
        ]

        rules: List[Rule] = []
        for index in range(num_rules):
            template = templates[index % len(templates)]
            rules.append(
                Rule(
                    condition=template.condition,
                    action=template.action,
                    name=f"{template.name}_{index}",
                )
            )
        return rules

    def mutate_rules(
        self,
        rules: List[Rule],
        feedback: str,
        inviolable_rules: List[Rule],
    ) -> List[Rule]:
        self._call_history.append(
            {
                "method": "mutate_rules",
                "feedback": feedback,
                "timestamp": datetime.now().isoformat(),
            }
        )
        return list(inviolable_rules) + [rule for rule in rules if not rule.inviolable]

    def evaluate_semantic_quality(
        self,
        rules: List[Rule],
    ) -> float:
        self._call_history.append(
            {
                "method": "evaluate_semantic_quality",
                "timestamp": datetime.now().isoformat(),
            }
        )
        base = 0.5 + min(len(rules), 10) * 0.02
        return max(0.0, min(1.0, base))

    def format_output(
        self,
        facts: Dict[str, Any],
        trace: List[Trace],
    ) -> str:
        self._call_history.append(
            {
                "method": "format_output",
                "timestamp": datetime.now().isoformat(),
            }
        )

        if facts.get("_blocked"):
            return facts.get("_block_reason", "Action blocked by safety constraints.")
        if facts.get("_halted"):
            return facts.get("_halt_reason", "System halted.")
        if "_last_output" in facts:
            return str(facts["_last_output"])
        if trace:
            return f"Action executed: {trace[-1].action}"
        return "No action taken."

    def get_call_history(self) -> List[Dict[str, Any]]:
        return list(self._call_history)

    def clear_call_history(self) -> None:
        self._call_history = []