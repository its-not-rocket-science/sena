"""Legacy research-prototype module (deprecated).

This module is preserved for historical context and backward compatibility only.
It is not part of the supported enterprise compliance engine.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List


def _normalise_expression(expression: str) -> str:
    """Convert friendly rule syntax into Python syntax."""
    expression = re.sub(r"\bAND\b", "and", expression)
    expression = re.sub(r"\bOR\b", "or", expression)
    expression = re.sub(r"\bNOT\b", "not", expression)
    expression = re.sub(r"\btrue\b", "True", expression, flags=re.IGNORECASE)
    expression = re.sub(r"\bfalse\b", "False", expression, flags=re.IGNORECASE)
    expression = re.sub(r"\bnull\b", "None", expression, flags=re.IGNORECASE)
    return expression


@dataclass(frozen=True)
class Rule:
    condition: str
    action: str
    rule_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str | None = None
    priority: int = 0
    inviolable: bool = False

    def evaluate(self, memory: Dict[str, Any]) -> bool:
        try:
            expression = _normalise_expression(self.condition)
            return bool(eval(expression, {"__builtins__": {}}, dict(memory)))
        except Exception:
            return False

    def execute(self, memory: Dict[str, Any]) -> Dict[str, Any]:
        updated = dict(memory)

        if self.action.startswith("SET:"):
            payload = self.action[4:].strip()
            if "=" in payload:
                key, raw_value = payload.split("=", 1)
                key = key.strip()
                raw_value = raw_value.strip()
                try:
                    value = json.loads(raw_value)
                except json.JSONDecodeError:
                    value = raw_value.strip("'\"")
                updated[key] = value

        elif self.action.startswith("OUTPUT:"):
            updated["_last_output"] = self.action[len("OUTPUT:"):].strip()

        elif self.action.startswith("BLOCK:"):
            updated["_blocked"] = True
            updated["_block_reason"] = self.action[len("BLOCK:"):].strip()

        elif self.action.startswith("HALT:"):
            updated["_halted"] = True
            updated["_halt_reason"] = self.action[len("HALT:"):].strip()

        elif self.action.startswith("CALL:"):
            updated["_pending_call"] = self.action[len("CALL:"):].strip()

        return updated

    def to_dict(self) -> Dict[str, Any]:
        return {
            "condition": self.condition,
            "action": self.action,
            "rule_id": self.rule_id,
            "name": self.name,
            "priority": self.priority,
            "inviolable": self.inviolable,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Rule":
        return cls(
            condition=data["condition"],
            action=data["action"],
            rule_id=data.get("rule_id", uuid.uuid4().hex[:8]),
            name=data.get("name"),
            priority=data.get("priority", 0),
            inviolable=data.get("inviolable", False),
        )


@dataclass
class Trace:
    iteration: int
    rule_id: str
    rule_name: str | None
    condition: str
    action: str
    working_memory_snapshot: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Genome:
    rules: List[Rule]
    fitness: float = 0.0

    def get_inviolable_rules(self) -> List[Rule]:
        return [rule for rule in self.rules if rule.inviolable]

    def get_evolvable_rules(self) -> List[Rule]:
        return [rule for rule in self.rules if not rule.inviolable]


WorkingMemory = Dict[str, Any]