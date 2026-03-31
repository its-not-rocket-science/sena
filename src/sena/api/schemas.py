from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EvaluateRequest(BaseModel):
    action_type: str
    request_id: str | None = None
    actor_id: str | None = None
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


class HealthResponse(BaseModel):
    status: Literal["ok"]
    bundle: BundleInfo
