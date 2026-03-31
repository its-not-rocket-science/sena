from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints


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


class BundleInfo(BaseModel):
    bundle_name: str
    version: str
    loaded_from: str
    owner: str | None = None
    description: str | None = None
    schema_version: str = "1"
    integrity_sha256: str | None = None
    policy_file_count: int = 0


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: Literal["sena-api"] = "sena-api"
    bundle: BundleInfo


class ReadinessResponse(BaseModel):
    status: Literal["ready"]
    checks: dict[str, Literal["ok"]]


class ErrorResponse(BaseModel):
    error: dict[str, Any]
