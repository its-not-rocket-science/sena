from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request

from sena.api.auth import evaluate_sensitive_operation
from sena.api.errors import raise_api_error
from sena.api.runtime import EngineState
from sena.api.schemas import ExceptionApproveRequest, ExceptionCreateRequest
from sena.services.exception_service import ExceptionCreateRequest as ServiceCreateRequest


ERROR_RESPONSES = {
    400: {"description": "Invalid exception request."},
    401: {"description": "Missing or invalid API key."},
    403: {"description": "API key is not authorized."},
    429: {"description": "Rate limit exceeded."},
    500: {"description": "Unexpected server error."},
}


def _serialize_exception(item) -> dict:
    payload = asdict(item)
    payload["expiry"] = item.expiry.isoformat()
    payload["approved_at"] = item.approved_at.isoformat() if item.approved_at else None
    return payload


def create_exceptions_router(state: EngineState) -> APIRouter:
    router = APIRouter(prefix="/exceptions", tags=["exceptions"], responses=ERROR_RESPONSES)

    @router.post("/create", summary="Create governed exception request")
    def create_exception(req: ExceptionCreateRequest) -> dict:
        try:
            created = state.exception_service.create(
                ServiceCreateRequest(
                    exception_id=req.exception_id,
                    action_type=req.scope.action_type,
                    actor=req.scope.actor,
                    attributes=req.scope.attributes,
                    expiry=req.expiry,
                    approver_class=req.approver_class,
                    justification=req.justification,
                )
            )
        except ValueError as exc:
            raise_api_error("http_bad_request", details={"reason": str(exc)})
        return {"exception": _serialize_exception(created)}

    @router.post("/approve", summary="Approve governed exception request")
    def approve_exception(req: ExceptionApproveRequest, request: Request) -> dict:
        principal = getattr(request.state, "auth_principal", None)
        decision = evaluate_sensitive_operation(
            operation="exception_approval",
            principal=principal,
            headers=request.headers,
            require_signed_step_up=state.settings.require_signed_step_up,
            step_up_hs256_secret=state.settings.step_up_hs256_secret,
            step_up_max_age_seconds=state.settings.step_up_max_age_seconds,
        )
        if not decision.allowed:
            raise_api_error("forbidden", details=decision.details())
        try:
            approved = state.exception_service.approve(
                exception_id=req.exception_id,
                approver_role=req.approver_role,
                approver_id=req.approver_id,
            )
        except ValueError as exc:
            raise_api_error("http_bad_request", details={"reason": str(exc)})
        return {"exception": _serialize_exception(approved)}

    @router.get("/active", summary="List active approved exceptions")
    def active_exceptions(as_of: datetime | None = Query(default=None)) -> dict:
        now = as_of or datetime.now(timezone.utc)
        items = state.exception_service.list_active(now=now)
        return {
            "as_of": now.isoformat(),
            "count": len(items),
            "exceptions": [_serialize_exception(item) for item in items],
        }

    return router
