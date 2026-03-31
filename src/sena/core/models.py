from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sena.core.enums import DecisionOutcome, RuleDecision, Severity


@dataclass
class ActionProposal:
    action_type: str
    request_id: str | None = None
    actor_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class PolicyRule:
    id: str
    description: str
    severity: Severity
    inviolable: bool
    applies_to: list[str]
    condition: dict[str, Any]
    decision: RuleDecision
    reason: str


@dataclass
class RuleEvaluationResult:
    rule_id: str
    matched: bool
    decision: RuleDecision | None = None
    inviolable: bool = False
    reason: str | None = None


@dataclass
class EvaluationTrace:
    action_type: str
    outcome: DecisionOutcome
    summary: str
    request_id: str | None = None
    applicable_rules: list[str] = field(default_factory=list)
    evaluated_rules: list[RuleEvaluationResult] = field(default_factory=list)
    matched_rules: list[RuleEvaluationResult] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
