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
class PolicyBundleMetadata:
    bundle_name: str
    version: str
    loaded_from: str


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
class DecisionReasoning:
    precedence_explanation: str
    summary: str


@dataclass
class AuditRecord:
    decision_id: str
    action_type: str
    request_id: str | None
    actor_id: str | None
    outcome: DecisionOutcome
    policy_bundle: PolicyBundleMetadata
    matched_rule_ids: list[str]
    evaluated_rule_ids: list[str]
    precedence_explanation: str


@dataclass
class EvaluationTrace:
    action_type: str
    outcome: DecisionOutcome
    summary: str
    decision_id: str
    decision: DecisionOutcome | None = None
    request_id: str | None = None
    policy_bundle: PolicyBundleMetadata | None = None
    reasoning: DecisionReasoning | None = None
    applicable_rules: list[str] = field(default_factory=list)
    evaluated_rules: list[RuleEvaluationResult] = field(default_factory=list)
    matched_rules: list[RuleEvaluationResult] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    audit_record: AuditRecord | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload["decision"] is None:
            payload["decision"] = payload["outcome"]
        return payload
