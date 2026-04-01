from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from sena.policy.validation import validate_identity_fields


NonEmptyStr = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


class EvaluateRequest(BaseModel):
    action_type: NonEmptyStr
    request_id: str | None = None
    actor_id: str | None = None
    actor_role: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
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
    bundle_id: int = Field(gt=0)
    target_lifecycle: Literal["candidate", "active", "deprecated"]
    promoted_by: NonEmptyStr
    promotion_reason: NonEmptyStr
    validation_artifact: str | None = None


class BundleRollbackRequest(BaseModel):
    bundle_name: NonEmptyStr
    to_bundle_id: int = Field(gt=0)
    promoted_by: NonEmptyStr
    promotion_reason: NonEmptyStr
    validation_artifact: NonEmptyStr


class BundleHistoryQuery(BaseModel):
    bundle_name: NonEmptyStr

