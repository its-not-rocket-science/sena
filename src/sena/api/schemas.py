from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from sena.core.enums import ActionOrigin
from sena.policy.validation import validate_identity_fields


NonEmptyStr = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


class EvaluateRequest(BaseModel):
    class RiskClassificationRequest(BaseModel):
        category: NonEmptyStr
        level: NonEmptyStr
        tags: list[str] = Field(default_factory=list)
        rationale: str | None = None

    class AIActionMetadataRequest(BaseModel):
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
        risk_classification: "EvaluateRequest.RiskClassificationRequest"

    class AutonomousMetadataRequest(BaseModel):
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
    ai_metadata: AIActionMetadataRequest | None = None
    autonomous_metadata: AutonomousMetadataRequest | None = None
    facts: dict[str, Any] = Field(default_factory=dict)
    default_decision: Literal["APPROVED", "BLOCKED", "ESCALATE", "ESCALATE_FOR_HUMAN_REVIEW"] = (
        "APPROVED"
    )
    strict_require_allow: bool = False

    @model_validator(mode="after")
    def validate_strict_identity_fields(self) -> "EvaluateRequest":
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
        if self.action_origin != ActionOrigin.AI_SUGGESTED and self.ai_metadata is not None:
            raise ValueError("ai_metadata is only valid for action_origin=ai_suggested")
        if self.action_origin == ActionOrigin.AUTONOMOUS_TOOL and self.autonomous_metadata is None:
            raise ValueError("action_origin=autonomous_tool requires autonomous_metadata")
        return self




class WebhookEvaluateRequest(BaseModel):
    provider: NonEmptyStr
    event_type: NonEmptyStr
    payload: dict[str, Any] = Field(default_factory=dict)
    facts: dict[str, Any] = Field(default_factory=dict)
    default_decision: Literal["APPROVED", "BLOCKED", "ESCALATE", "ESCALATE_FOR_HUMAN_REVIEW"] = (
        "APPROVED"
    )
    strict_require_allow: bool = False

class BatchEvaluateRequest(BaseModel):
    items: list[EvaluateRequest] = Field(min_length=1, max_length=500)


class SimulationScenarioRequest(BaseModel):
    scenario_id: NonEmptyStr
    action_type: NonEmptyStr
    request_id: str | None = None
    actor_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    facts: dict[str, Any] = Field(default_factory=dict)
    source_system: str | None = None
    workflow_stage: str | None = None
    risk_category: str | None = None


class SimulationRequest(BaseModel):
    baseline_policy_dir: NonEmptyStr
    candidate_policy_dir: NonEmptyStr
    scenarios: list[SimulationScenarioRequest] = Field(min_length=1)


class BundleInfo(BaseModel):
    bundle_name: str
    version: str
    loaded_from: str
    owner: str | None = None
    description: str | None = None
    schema_version: str = "1"
    lifecycle: str = "draft"
    integrity_sha256: str | None = None
    policy_file_count: int = 0
    context_schema: dict[str, str] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: Literal["sena-api"] = "sena-api"
    bundle: BundleInfo


class ReadinessResponse(BaseModel):
    status: Literal["ready"]
    checks: dict[str, Literal["ok"]]
    mode: str


class ErrorResponse(BaseModel):
    error: dict[str, Any]


class BundleRegisterRequest(BaseModel):
    policy_dir: str | None = None
    bundle_name: str | None = None
    bundle_version: str | None = None
    lifecycle: Literal["draft", "candidate", "active", "deprecated"] = "draft"
    created_by: NonEmptyStr = "system"
    creation_reason: str | None = None
    source_bundle_id: int | None = Field(default=None, gt=0)
    compatibility_notes: str | None = None
    release_notes: str | None = None
    migration_notes: str | None = None


class BundlePromoteRequest(BaseModel):
    class PromotionThresholds(BaseModel):
        max_changed_outcomes: int | None = Field(default=None, ge=0)
        max_block_to_approve_regressions: int | None = Field(default=None, ge=0)
        max_missing_scenario_coverage: int | None = Field(default=None, ge=0)
        max_changed_risk_categories: dict[str, int] = Field(default_factory=dict)
        required_risk_categories: list[str] = Field(default_factory=list)

    bundle_id: int = Field(gt=0)
    target_lifecycle: Literal["candidate", "active", "deprecated"]
    promoted_by: NonEmptyStr
    promotion_reason: NonEmptyStr
    validation_artifact: str | None = None
    simulation_scenarios: list[SimulationScenarioRequest] = Field(default_factory=list)
    simulation_result: dict[str, Any] | None = None
    thresholds: PromotionThresholds | None = None
    break_glass: bool = False
    break_glass_reason: str | None = None


class BundleRollbackRequest(BaseModel):
    bundle_name: NonEmptyStr
    to_bundle_id: int = Field(gt=0)
    promoted_by: NonEmptyStr
    promotion_reason: NonEmptyStr
    validation_artifact: NonEmptyStr


class BundleHistoryQuery(BaseModel):
    bundle_name: NonEmptyStr
