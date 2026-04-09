from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from sena.core.enums import ActionOrigin, DecisionOutcome
from sena.core.models import (
    AIActionMetadata,
    ActionProposal,
    AutonomousToolMetadata,
    RiskClassification,
)
from sena.policy.validation import validate_identity_fields

NonEmptyStr = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


class EvaluatePayload(BaseModel):
    """Shared evaluate payload schema used by API and CLI."""

    class RiskClassificationPayload(BaseModel):
        category: NonEmptyStr
        level: NonEmptyStr
        tags: list[str] = Field(default_factory=list)
        rationale: str | None = None

    class AIActionMetadataPayload(BaseModel):
        originating_system: NonEmptyStr
        originating_model: str | None = None
        prompt_context_ref: NonEmptyStr
        confidence: float | None = None
        uncertainty: str | None = None
        requested_tool: str | None = None
        requested_action: NonEmptyStr
        evidence_references: list[NonEmptyStr] = Field(min_length=1)
        citation_references: list[str] = Field(default_factory=list)
        human_requester: NonEmptyStr
        human_owner: NonEmptyStr
        human_approver: str | None = None
        risk_classification: "EvaluatePayload.RiskClassificationPayload"

    class AutonomousMetadataPayload(BaseModel):
        tool_name: NonEmptyStr
        trigger_type: NonEmptyStr
        trigger_reference: str | None = None
        supervising_owner: str | None = None

    action_type: NonEmptyStr
    request_id: str | None = None
    actor_id: str | None = None
    actor_role: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    action_origin: ActionOrigin = ActionOrigin.HUMAN
    ai_metadata: AIActionMetadataPayload | None = None
    autonomous_metadata: AutonomousMetadataPayload | None = None
    facts: dict[str, Any] = Field(default_factory=dict)
    default_decision: Literal[
        "APPROVED", "BLOCKED", "ESCALATE", "ESCALATE_FOR_HUMAN_REVIEW"
    ] = "APPROVED"
    strict_require_allow: bool = False
    dry_run: bool = False
    simulate_exceptions: bool = False

    @model_validator(mode="after")
    def validate_strict_identity_fields(self) -> "EvaluatePayload":
        if self.strict_require_allow:
            missing = validate_identity_fields(self.actor_id, self.actor_role)
            if missing:
                missing_label = ", ".join(missing)
                raise ValueError(
                    f"strict_require_allow=true requires identity fields: {missing_label}"
                )
        if self.action_origin == ActionOrigin.AI_SUGGESTED and self.ai_metadata is None:
            raise ValueError(
                "action_origin=ai_suggested requires ai_metadata with deterministic governance fields"
            )
        if (
            self.action_origin != ActionOrigin.AI_SUGGESTED
            and self.ai_metadata is not None
        ):
            raise ValueError("ai_metadata is only valid for action_origin=ai_suggested")
        if (
            self.action_origin == ActionOrigin.AUTONOMOUS_TOOL
            and self.autonomous_metadata is None
        ):
            raise ValueError(
                "action_origin=autonomous_tool requires autonomous_metadata"
            )
        return self

    def resolved_request_id(self, fallback_request_id: str) -> str:
        return self.request_id or fallback_request_id

    def to_default_decision(self) -> DecisionOutcome:
        if self.default_decision == "ESCALATE":
            return DecisionOutcome.ESCALATE_FOR_HUMAN_REVIEW
        return DecisionOutcome(self.default_decision)

    def to_action_proposal(self, fallback_request_id: str) -> ActionProposal:
        normalized_ai_metadata = None
        if self.ai_metadata is not None:
            risk = self.ai_metadata.risk_classification
            normalized_ai_metadata = AIActionMetadata(
                originating_system=self.ai_metadata.originating_system,
                originating_model=self.ai_metadata.originating_model,
                prompt_context_ref=self.ai_metadata.prompt_context_ref,
                confidence=self.ai_metadata.confidence,
                uncertainty=self.ai_metadata.uncertainty,
                requested_tool=self.ai_metadata.requested_tool,
                requested_action=self.ai_metadata.requested_action,
                evidence_references=list(self.ai_metadata.evidence_references),
                citation_references=list(self.ai_metadata.citation_references),
                human_requester=self.ai_metadata.human_requester,
                human_owner=self.ai_metadata.human_owner,
                human_approver=self.ai_metadata.human_approver,
                risk_classification=RiskClassification(**risk.model_dump()),
            )
        normalized_autonomous_metadata = None
        if self.autonomous_metadata is not None:
            normalized_autonomous_metadata = AutonomousToolMetadata(
                **self.autonomous_metadata.model_dump()
            )

        return ActionProposal(
            action_type=self.action_type,
            request_id=self.resolved_request_id(fallback_request_id),
            actor_id=self.actor_id,
            actor_role=self.actor_role,
            attributes=self.attributes,
            action_origin=self.action_origin,
            ai_metadata=normalized_ai_metadata,
            autonomous_metadata=normalized_autonomous_metadata,
        )

    def to_replay_input(self, fallback_request_id: str) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "request_id": self.resolved_request_id(fallback_request_id),
            "actor_id": self.actor_id,
            "actor_role": self.actor_role,
            "attributes": self.attributes,
            "facts": self.facts,
        }
