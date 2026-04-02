from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable

from sena.core.enums import ActionOrigin, DecisionOutcome, RuleDecision, Severity


@dataclass
class RiskClassification:
    category: str
    level: str
    tags: list[str] = field(default_factory=list)
    rationale: str | None = None


@dataclass
class AIActionMetadata:
    originating_system: str
    originating_model: str | None = None
    prompt_context_ref: str | None = None
    confidence: float | None = None
    uncertainty: str | None = None
    requested_tool: str | None = None
    requested_action: str | None = None
    evidence_references: list[str] = field(default_factory=list)
    citation_references: list[str] = field(default_factory=list)
    human_requester: str | None = None
    human_owner: str | None = None
    human_approver: str | None = None
    risk_classification: RiskClassification | None = None


@dataclass
class AutonomousToolMetadata:
    tool_name: str
    trigger_type: str
    trigger_reference: str | None = None
    supervising_owner: str | None = None


@dataclass
class ActionProposal:
    action_type: str
    request_id: str | None = None
    actor_id: str | None = None
    actor_role: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    action_origin: ActionOrigin = ActionOrigin.HUMAN
    ai_metadata: AIActionMetadata | None = None
    autonomous_metadata: AutonomousToolMetadata | None = None


@dataclass
class PolicyBundleMetadata:
    bundle_name: str
    version: str
    loaded_from: str
    lifecycle: str = "draft"
    owner: str | None = None
    description: str | None = None
    schema_version: str = "1"
    integrity_sha256: str | None = None
    policy_file_count: int = 0
    context_schema: dict[str, str] = field(default_factory=dict)
    invariants: list["PolicyInvariant"] = field(default_factory=list)


@dataclass
class PolicyInvariant:
    id: str
    description: str
    applies_to: list[str]
    condition: dict[str, Any]
    reason: str


@dataclass
class InvariantEvaluationResult:
    invariant_id: str
    matched: bool
    reason: str | None = None


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
    required_evidence: list[str] = field(default_factory=list)
    missing_evidence_decision: RuleDecision | None = None


@dataclass
class RuleEvaluationResult:
    rule_id: str
    matched: bool
    decision: RuleDecision | None = None
    inviolable: bool = False
    reason: str | None = None
    required_evidence: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvaluatorConfig:
    default_decision: DecisionOutcome = DecisionOutcome.APPROVED
    require_allow_match: bool = False
    enforce_context_schema: bool = True
    on_escalation: Callable[["EvaluationTrace"], None] | None = None


@dataclass
class DecisionReasoning:
    precedence_explanation: str
    summary: str
    outcome_rationale: list[str] = field(default_factory=list)
    matched_controls: list[dict[str, Any]] = field(default_factory=list)
    matched_invariants: list[dict[str, Any]] = field(default_factory=list)
    risk_summary: dict[str, Any] = field(default_factory=dict)
    reviewer_guidance: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditRecord:
    decision_id: str
    timestamp: datetime
    write_timestamp: datetime | None
    event_type: str
    action_type: str
    request_id: str | None
    actor_id: str | None
    actor_role: str | None
    outcome: DecisionOutcome
    policy_bundle: PolicyBundleMetadata
    matched_rule_ids: list[str]
    evaluated_rule_ids: list[str]
    missing_fields: list[str]
    precedence_explanation: str
    input_fingerprint: str
    decision_hash: str
    source_metadata: dict[str, Any] = field(default_factory=dict)
    request_correlation_id: str | None = None
    evaluator_version: str | None = None
    policy_bundle_release_id: str | None = None
    storage_sequence_number: int | None = None
    chain_hash: str | None = None
    previous_chain_hash: str | None = None


@dataclass
class EvaluationTrace:
    action_type: str
    outcome: DecisionOutcome
    summary: str
    decision_id: str
    decision: DecisionOutcome | None = None
    decision_timestamp: datetime | None = None
    decision_hash: str | None = None
    request_id: str | None = None
    policy_bundle: PolicyBundleMetadata | None = None
    reasoning: DecisionReasoning | None = None
    applicable_rules: list[str] = field(default_factory=list)
    evaluated_rules: list[RuleEvaluationResult] = field(default_factory=list)
    matched_rules: list[RuleEvaluationResult] = field(default_factory=list)
    evaluated_invariants: list[InvariantEvaluationResult] = field(default_factory=list)
    matched_invariants: list[InvariantEvaluationResult] = field(default_factory=list)
    conflicting_rules: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    audit_record: AuditRecord | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload["decision"] is None:
            payload["decision"] = payload["outcome"]
        return payload
