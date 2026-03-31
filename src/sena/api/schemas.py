from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EvaluateRequest(BaseModel):
    action_type: str
    request_id: str | None = None
    actor_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    facts: dict[str, Any] = Field(default_factory=dict)


class BundleInfo(BaseModel):
    bundle_name: str
    version: str
    loaded_from: str


class HealthResponse(BaseModel):
    status: Literal["ok"]
    bundle: BundleInfo
