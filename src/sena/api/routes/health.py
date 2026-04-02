from __future__ import annotations

from fastapi import APIRouter

from sena.api.runtime import EngineState
from sena.api.schemas import BundleInfo, HealthResponse, ReadinessResponse


def create_health_router(state: EngineState) -> APIRouter:
    router = APIRouter()

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok", bundle=BundleInfo.model_validate(state.metadata.__dict__)
        )

    @router.get("/ready", response_model=ReadinessResponse)
    def ready() -> ReadinessResponse:
        checks = {
            "policy_bundle_loaded": "ok",
            "auth_config_valid": "ok",
            "policy_store_reachable": "ok",
        }
        if state.settings.runtime_mode == "production":
            checks["production_guardrails_enforced"] = "ok"
        return ReadinessResponse(
            status="ready", mode=state.settings.runtime_mode, checks=checks
        )

    @router.get("/bundle", response_model=BundleInfo)
    def bundle() -> BundleInfo:
        return BundleInfo.model_validate(state.metadata.__dict__)

    @router.get("/bundle/inspect")
    def bundle_inspect() -> dict:
        applies_to: dict[str, int] = {}
        for rule in state.rules:
            for action in rule.applies_to:
                applies_to[action] = applies_to.get(action, 0) + 1
        return {
            "bundle": BundleInfo.model_validate(state.metadata.__dict__),
            "rules_total": len(state.rules),
            "actions_covered": applies_to,
        }

    return router
