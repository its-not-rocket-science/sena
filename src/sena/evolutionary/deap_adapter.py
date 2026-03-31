from __future__ import annotations

import logging
import random
from typing import Callable, List, Optional, Sequence, Tuple

from sena.core.types import Genome, Rule

logger = logging.getLogger(__name__)


class DEAPAdapter:
    def __init__(self, population_size: int = 10) -> None:
        self.population: List[Genome] = []
        self.population_size = population_size
        self.generation = 0
        self._inviolable_prototypes: List[Rule] = []

    def initialise_population(
        self,
        templates: Sequence[Tuple[str, str]],
        num_rules_range: Tuple[int, int] = (5, 5),
    ) -> List[Genome]:
        self.population = []
        self.generation = 0

        min_rules, max_rules = num_rules_range
        if min_rules > max_rules:
            min_rules, max_rules = max_rules, min_rules

        for _ in range(self.population_size):
            rule_count = random.randint(min_rules, max_rules)
            rules = [Rule(*random.choice(list(templates))) for _ in range(rule_count)]
            self.population.append(Genome(self._inviolable_prototypes + rules))

        logger.info("Initialised population with %s individuals", len(self.population))
        return list(self.population)

    def evaluate_population(self, fn: Callable[[Genome], float]) -> List[Genome]:
        for genome in self.population:
            score = fn(genome)
            genome.fitness = float(getattr(score, "primary", score))
        return list(self.population)

    def evolve_generation(self) -> List[Genome]:
        self.population.sort(key=lambda genome: genome.fitness, reverse=True)
        self.generation += 1
        logger.debug("Generation %s evolved", self.generation)
        return list(self.population)

    def set_inviolable_prototypes(self, rules: List[Rule]) -> None:
        self._inviolable_prototypes = list(rules)
        logger.info("Set %s inviolable prototype rules", len(rules))

    def get_population(self) -> List[Genome]:
        return list(self.population)

    def get_best_individual(self) -> Optional[Genome]:
        if not self.population:
            return None
        return max(self.population, key=lambda genome: genome.fitness)