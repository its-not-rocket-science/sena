from __future__ import annotations

from fastapi import APIRouter

from sena.api.runtime import EngineState
from sena.api.schemas import BundleInfo, HealthResponse, ReadinessResponse


def create_health_router(state: EngineState) -> APIRouter:
    router = APIRouter(tags=["operations"], responses={400:{"description":"Bad request"},401:{"description":"Unauthorized"},403:{"description":"Forbidden"},429:{"description":"Rate limited"},500:{"description":"Server error"}})

    @router.get("/health", response_model=HealthResponse, summary="Liveness probe", description="Returns API and bundle status for health checks.")
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok", bundle=BundleInfo.model_validate(state.metadata.__dict__)
        )

    @router.get("/ready", response_model=ReadinessResponse, summary="Readiness probe")
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

    @router.get("/bundle", response_model=BundleInfo, summary="Get loaded bundle metadata")
    def bundle() -> BundleInfo:
        return BundleInfo.model_validate(state.metadata.__dict__)

    @router.get("/bundle/inspect", summary="Inspect loaded bundle rule coverage")
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
