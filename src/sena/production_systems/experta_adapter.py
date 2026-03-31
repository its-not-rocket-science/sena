from dataclasses import replace
from typing import List, Tuple

from sena.core.types import Rule, WorkingMemory, Trace


class ExpertaAdapter:
    def __init__(self) -> None:
        self.rules: List[Rule] = []

    def add_rule(self, rule: Rule, inviolable: bool = False) -> None:
        stored_rule = replace(rule, inviolable=inviolable or rule.inviolable)
        self.rules.append(stored_rule)

    def get_rules(self) -> List[Rule]:
        return list(self.rules)

    def get_inviolable_rules(self) -> List[Rule]:
        return [rule for rule in self.rules if rule.inviolable]

    def remove_rule(self, rule_id: str) -> bool:
        for index, rule in enumerate(self.rules):
            if getattr(rule, "rule_id", None) == rule_id:
                if rule.inviolable:
                    return False
                del self.rules[index]
                return True
        return False

    def clear_rules(self, preserve_inviolable: bool = True) -> None:
        if preserve_inviolable:
            self.rules = [rule for rule in self.rules if rule.inviolable]
        else:
            self.rules = []

    def infer(self, memory: WorkingMemory) -> Tuple[WorkingMemory, List[Trace]]:
        updated = dict(memory)
        trace: List[Trace] = []

        ordered_rules = sorted(
            self.rules,
            key=lambda rule: (rule.inviolable, rule.priority),
            reverse=True,
        )

        for iteration, rule in enumerate(ordered_rules, start=1):
            if rule.evaluate(updated):
                trace.append(
                    Trace(
                        iteration=iteration,
                        rule_id=rule.rule_id,
                        rule_name=rule.name,
                        condition=rule.condition,
                        action=rule.action,
                        working_memory_snapshot=dict(updated),
                    )
                )
                updated = rule.execute(updated)

                if updated.get("_blocked") or updated.get("_halted"):
                    break

        return updated, trace
