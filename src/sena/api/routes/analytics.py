from __future__ import annotations

from fastapi import APIRouter

from sena.api.errors import raise_api_error
from sena.api.runtime import EngineState
from sena.services.policy_analytics import PolicyEfficacyAnalytics


def create_analytics_router(state: EngineState) -> APIRouter:
    router = APIRouter(tags=["analytics"])

    @router.get(
        "/analytics/policy-efficacy",
        summary="Policy efficacy metrics",
        description=(
            "Returns policy efficacy computed from audit records, including "
            "downstream outcome rates and incident rates."
        ),
    )
    def policy_efficacy() -> dict:
        if not state.settings.audit_sink_jsonl:
            raise_api_error("audit_sink_not_configured")
        return PolicyEfficacyAnalytics(state.settings.audit_sink_jsonl).compute()

    return router
