"""Legacy research-prototype module (deprecated).

This module is preserved for historical context and backward compatibility only.
It is not part of the supported enterprise compliance engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sena.legacy.core.types import Genome, Rule, WorkingMemory


@dataclass
class TrainingHistory:
    generation: int
    best_fitness: float
    population_avg_fitness: float
    num_rules_best: int


class SENA:
    def __init__(
        self,
        production_system,
        evolutionary_algorithm,
        llm,
        inviolable_rules: Optional[List[Rule]] = None,
    ) -> None:
        self.ps = production_system
        self.ea = evolutionary_algorithm
        self.llm = llm
        self._inviolable_rules = list(inviolable_rules or [])
        self._training_history: List[TrainingHistory] = []
        self._best_genome: Optional[Genome] = None
        self._last_evaluation: Optional[Dict[str, Any]] = None

        for rule in self._inviolable_rules:
            self.ps.add_rule(rule, inviolable=True)

        if self._inviolable_rules and hasattr(self.ea, "set_inviolable_prototypes"):
            self.ea.set_inviolable_prototypes(self._inviolable_rules)

    def initialise_from_domain(self, domain_description: str, num_initial_rules: int = 10) -> None:
        rules = self.llm.generate_rules(domain_description, num_initial_rules)
        templates = [(rule.condition, rule.action) for rule in rules]
        self.ea.initialise_population(templates)

    def train(
        self,
        test_scenarios: List[Dict[str, Any]],
        generations: int = 1,
        use_llm_mutation: bool = False,
        llm_mutation_interval: int = 5,
    ) -> List[TrainingHistory]:
        self._training_history = []

        for generation in range(1, generations + 1):
            def fitness_fn(genome: Genome) -> float:
                score = 0.0
                for scenario in test_scenarios:
                    result = self._run_genome(genome, scenario.get("initial_memory", {}))
                    if scenario.get("expects_block"):
                        score += 1.0 if result["blocked"] else 0.0
                    else:
                        score += 1.0 if not result["blocked"] else 0.0
                if test_scenarios:
                    score /= len(test_scenarios)
                return score

            self.ea.evaluate_population(fitness_fn)
            best = self.ea.get_best_individual()
            population = self.ea.get_population()

            if best is not None and population:
                avg = sum(genome.fitness for genome in population) / len(population)
                self._best_genome = best
                self._training_history.append(
                    TrainingHistory(
                        generation=generation,
                        best_fitness=best.fitness,
                        population_avg_fitness=avg,
                        num_rules_best=len(best.rules),
                    )
                )

            self.ea.evolve_generation()

        return list(self._training_history)

    def _run_genome(self, genome: Genome, initial_memory: WorkingMemory) -> Dict[str, Any]:
        self.ps.clear_rules(preserve_inviolable=False)
        for rule in genome.rules:
            self.ps.add_rule(rule, inviolable=rule.inviolable)

        final_memory, trace = self.ps.infer(dict(initial_memory))
        output = self.llm.format_output(final_memory, trace)

        return {
            "output": output,
            "trace": trace,
            "final_working_memory": final_memory,
            "num_rules_fired": len(trace),
            "blocked": final_memory.get("_blocked", False),
            "halted": final_memory.get("_halted", False),
        }

    def evaluate(self, initial_memory: WorkingMemory) -> Dict[str, Any]:
        if self._best_genome is None:
            raise ValueError("System not trained. Call train() first.")

        result = self._run_genome(self._best_genome, initial_memory)
        self._last_evaluation = result
        return result

    def explain_decision(self, initial_memory: Optional[WorkingMemory] = None) -> str:
        if initial_memory is not None:
            result = self.evaluate(initial_memory)
        elif self._last_evaluation is not None:
            result = self._last_evaluation
        else:
            return "No evaluation available. Run evaluate() first."

        lines = [
            "=" * 50,
            "SENA Decision Explanation",
            "=" * 50,
        ]

        if result.get("blocked"):
            lines.append("")
            lines.append("ACTION BLOCKED BY SAFETY CONSTRAINTS")

        if result.get("halted"):
            lines.append("")
            lines.append("SYSTEM HALTED")

        lines.append("")
        lines.append("Inference Trace:")

        for step in result["trace"]:
            lines.append(f"  Step {step.iteration}:")
            lines.append(f"    Rule: {step.rule_id}")
            lines.append(f"    Condition: {step.condition}")
            lines.append(f"    Action: {step.action}")

        lines.append("")
        lines.append(f"Final Output: {result['output']}")
        lines.append(f"Rules Fired: {result['num_rules_fired']}")

        return "\n".join(lines)

    def get_training_history(self) -> List[TrainingHistory]:
        return list(self._training_history)

    def get_best_genome(self) -> Optional[Genome]:
        return self._best_genome