from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from sena.api.dependencies import check_idempotency_key, persist_idempotency_response
from sena.api.errors import raise_api_error
from sena.api.runtime import EngineState, parse_default_decision
from sena.api.schemas import (
    BatchEvaluateRequest,
    EvaluateRequest,
    ReplayDriftRequest,
    SimulationReplayRequest,
    SimulationRequest,
)
from sena.services.audit_service import AuditService
from sena.services.evaluation_service import EvaluationService
from sena.services.reliability_service import QueueOverflowError

ERROR_RESPONSES = {
    400: {"description": "Invalid request or evaluation failure."},
    401: {"description": "Missing or invalid API key."},
    403: {"description": "API key is not authorized."},
    429: {"description": "Rate limit exceeded."},
    500: {"description": "Unexpected server error."},
}


def create_evaluate_router(state: EngineState) -> APIRouter:
    router = APIRouter(tags=["evaluation"], responses=ERROR_RESPONSES)
    evaluation_service = EvaluationService(
        state=state, audit_service=AuditService(state.settings.audit_sink_jsonl)
    )

    def _evaluate(req: EvaluateRequest, request: Request) -> dict:
        try:
            return state.processing_service.enqueue_and_process(
                {
                    "event_type": "evaluate",
                    "payload": req.model_dump(),
                    "request_id": request.state.request_id,
                }
            )
        except QueueOverflowError as exc:
            raise_api_error("rate_limited", details={"reason": str(exc)})
        except Exception as exc:  # pragma: no cover
            state.processing_store.enqueue_dead_letter(
                {
                    "event_type": "evaluate",
                    "payload": req.model_dump(),
                    "request_id": request.state.request_id,
                },
                str(exc),
            )
            raise_api_error("evaluation_error", details={"reason": str(exc)})

    @router.post(
        "/evaluate",
        summary="Evaluate one action proposal",
        description="Returns the policy decision trace for one action proposal.",
    )
    def evaluate(
        req: EvaluateRequest,
        request: Request,
        idempotent_response: Response | None = Depends(check_idempotency_key),
    ) -> dict | Response:
        if idempotent_response is not None:
            return idempotent_response
        result = _evaluate(req, request)
        if req.dry_run:
            result["dry_run"] = True
        persist_idempotency_response(request, result)
        return result

    @router.post(
        "/evaluate/review-package",
        summary="Evaluate and generate review package",
        description="Runs evaluation and returns a deterministic decision-review package.",
    )
    def evaluate_review_package(req: EvaluateRequest, request: Request) -> dict:
        try:
            proposal = evaluation_service.build_action_proposal(
                action_type=req.action_type,
                request_id=req.request_id or request.state.request_id,
                actor_id=req.actor_id,
                actor_role=req.actor_role,
                attributes=req.attributes,
                action_origin=req.action_origin,
                ai_metadata=req.ai_metadata.model_dump() if req.ai_metadata else None,
                autonomous_metadata=req.autonomous_metadata.model_dump()
                if req.autonomous_metadata
                else None,
            )
            return evaluation_service.evaluate_review_package(
                proposal=proposal,
                facts=req.facts,
                endpoint="/v1/evaluate/review-package",
                default_decision=parse_default_decision(req.default_decision),
                strict_require_allow=req.strict_require_allow,
            )
        except Exception as exc:  # pragma: no cover
            raise_api_error("evaluation_error", details={"reason": str(exc)})

    @router.post(
        "/evaluate/batch",
        summary="Evaluate a batch",
        description="Evaluates up to 500 requests and returns ordered results.",
    )
    def evaluate_batch(req: BatchEvaluateRequest, request: Request) -> dict:
        return {
            "count": len(req.items),
            "results": [_evaluate(item, request) for item in req.items],
        }

    @router.post("/simulation", summary="Simulate bundle impact")
    def simulation(req: SimulationRequest) -> dict:
        return evaluation_service.simulate_policy_change(
            baseline_policy_dir=req.baseline_policy_dir,
            candidate_policy_dir=req.candidate_policy_dir,
            scenarios=[item.model_dump() for item in req.scenarios],
        )

    @router.post("/replay/drift", summary="Replay historical payloads for drift")
    def replay_drift(req: ReplayDriftRequest) -> dict:
        return evaluation_service.replay_policy_drift(
            replay_payload=req.replay_payload,
            baseline_policy_dir=req.baseline_policy_dir,
            candidate_policy_dir=req.candidate_policy_dir,
            baseline_mapping_mode=req.baseline_mapping_mode,
            baseline_mapping_config_path=req.baseline_mapping_config_path,
            candidate_mapping_mode=req.candidate_mapping_mode,
            candidate_mapping_config_path=req.candidate_mapping_config_path,
        )

    @router.post("/simulation/replay", summary="Replay recent audit traffic")
    def simulation_replay(req: SimulationReplayRequest) -> dict:
        window_seconds = 3600 if req.window == "last_1_hour" else 86400
        try:
            return evaluation_service.replay_recent_traffic(
                audit_path=state.settings.audit_sink_jsonl,
                proposed_policy_dir=req.proposed_policy_dir,
                window_seconds=window_seconds,
                max_samples=req.max_samples,
            )
        except ValueError as exc:
            raise_api_error("http_bad_request", details={"reason": str(exc)})

    @router.get(
        "/decision/{decision_id}/explanation",
        summary="Export decision explanation",
        description=(
            "Returns a role-specific explanation object. "
            "Use view=analyst for concise output or view=auditor for full trace."
        ),
    )
    def get_decision_explanation(
        decision_id: str,
        view: str = Query(default="auditor", pattern="^(analyst|auditor)$"),
    ) -> dict:
        stored = state.processing_store.get_decision_explanation(decision_id)
        if stored is None:
            raise_api_error(
                "http_not_found",
                message=f"Decision explanation not found for '{decision_id}'.",
            )
        payload = stored.get(view)
        if not isinstance(payload, dict):
            raise_api_error(
                "http_not_found",
                message=(
                    f"Decision explanation view '{view}' not found for '{decision_id}'."
                ),
            )
        return payload

    return router
