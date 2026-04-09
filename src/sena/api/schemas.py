from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ConfigDict, model_validator

from sena.api.errors import SenaErrorResponse
from sena.schemas import EvaluatePayload, NonEmptyStr


class EvaluateRequest(EvaluatePayload):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "action_type": "approve_vendor_payment",
                "request_id": "req-123",
                "actor_id": "user-42",
                "actor_role": "finance_analyst",
                "attributes": {"amount": 12000, "vendor_verified": False},
                "facts": {"risk_score": 91},
                "default_decision": "APPROVED",
                "strict_require_allow": False,
                "dry_run": False,
            }
        }
    )


class WebhookEvaluateRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"provider": "jira", "event_type": "issue_updated", "payload": {"id": "ISSUE-101"}, "facts": {}, "default_decision": "APPROVED", "strict_require_allow": False}})
    provider: NonEmptyStr
    event_type: NonEmptyStr
    tenant_id: str | None = None
    region: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    facts: dict[str, Any] = Field(default_factory=dict)
    default_decision: Literal[
        "APPROVED", "BLOCKED", "ESCALATE", "ESCALATE_FOR_HUMAN_REVIEW"
    ] = "APPROVED"
    strict_require_allow: bool = False
    downstream_outcome: Literal["success", "failure"] | None = None
    incident_flag: bool | None = None


class BatchEvaluateRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"items": [{"action_type": "approve_vendor_payment", "attributes": {"amount": 500, "vendor_verified": True}}]}})
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


class ReplayDriftRequest(BaseModel):
    replay_payload: dict[str, Any]
    baseline_policy_dir: NonEmptyStr
    candidate_policy_dir: str | None = None
    baseline_mapping_mode: Literal["jira", "servicenow", "webhook"] | None = None
    baseline_mapping_config_path: str | None = None
    candidate_mapping_mode: Literal["jira", "servicenow", "webhook"] | None = None
    candidate_mapping_config_path: str | None = None


class SimulationReplayRequest(BaseModel):
    proposed_policy_dir: NonEmptyStr
    window: Literal["last_1_hour", "last_1_day"] = "last_1_hour"
    max_samples: int = Field(default=10, ge=1, le=100)


class ExceptionScopeRequest(BaseModel):
    action_type: NonEmptyStr
    actor: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class ExceptionCreateRequest(BaseModel):
    exception_id: NonEmptyStr
    scope: ExceptionScopeRequest
    expiry: datetime
    approver_class: NonEmptyStr
    justification: NonEmptyStr


class ExceptionApproveRequest(BaseModel):
    exception_id: NonEmptyStr
    approver_role: NonEmptyStr
    approver_id: NonEmptyStr


class ExceptionActiveQuery(BaseModel):
    as_of: datetime | None = None


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
    error: SenaErrorResponse


class BundleRegisterRequest(BaseModel):
    policy_dir: str | None = None
    bundle_name: str | None = None
    bundle_version: str | None = None
    lifecycle: Literal["draft", "candidate", "approved", "active", "deprecated"] = "draft"
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
        max_regressions_by_outcome_type: dict[str, int] = Field(default_factory=dict)
        max_missing_scenario_coverage: int | None = Field(default=None, ge=0)
        max_changed_risk_categories: dict[str, int] = Field(default_factory=dict)
        required_risk_categories: list[str] = Field(default_factory=list)

    bundle_id: int = Field(gt=0)
    target_lifecycle: Literal["candidate", "approved", "active", "deprecated"]
    promoted_by: NonEmptyStr
    promotion_reason: NonEmptyStr
    validation_artifact: str | None = None
    simulation_scenarios: list[SimulationScenarioRequest] = Field(default_factory=list)
    simulation_result: dict[str, Any] | None = None
    thresholds: PromotionThresholds | None = None
    break_glass: bool = False
    break_glass_reason: str | None = None
    approver_attestations: list[str] = Field(default_factory=list)


class BundleRollbackRequest(BaseModel):
    bundle_name: NonEmptyStr
    to_bundle_id: int | None = Field(default=None, gt=0)
    version: str | None = None
    promoted_by: NonEmptyStr
    promotion_reason: NonEmptyStr
    validation_artifact: NonEmptyStr
    preview_only: bool = False
    simulation_scenarios: list[SimulationScenarioRequest] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_target(self) -> "BundleRollbackRequest":
        if self.to_bundle_id is None and not self.version:
            raise ValueError("rollback requires either to_bundle_id or version")
        if self.to_bundle_id is not None and self.version:
            raise ValueError("rollback target must specify only one of to_bundle_id or version")
        return self


class BundleHistoryQuery(BaseModel):
    bundle_name: NonEmptyStr


class AuditTreeVerifyRequest(BaseModel):
    decision_id: NonEmptyStr
    merkle_proof: list[NonEmptyStr]
    expected_root: NonEmptyStr
