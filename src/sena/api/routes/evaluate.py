from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from sena.api.dependencies import check_idempotency_key, persist_idempotency_response
from sena.api.errors import raise_api_error
from sena.api.runtime import EngineState, parse_default_decision
from sena.api.schemas import (
    BatchEvaluateRequest,
    EvaluateRequest,
    ReplayDriftRequest,
    SimulationRequest,
)
from sena.services.audit_service import AuditService
from sena.services.evaluation_service import EvaluationService


def create_evaluate_router(state: EngineState) -> APIRouter:
    router = APIRouter()
    evaluation_service = EvaluationService(
        state=state, audit_service=AuditService(state.settings.audit_sink_jsonl)
    )

    def _evaluate(req: EvaluateRequest, request: Request) -> dict:
        try:
            return state.processing_service.process_evaluate(
                req.model_dump(),
                request_id=request.state.request_id,
            )
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

    @router.post("/evaluate")
    def evaluate(
        req: EvaluateRequest,
        request: Request,
        idempotent_response: Response | None = Depends(check_idempotency_key),
    ) -> dict | Response:
        if idempotent_response is not None:
            return idempotent_response
        result = _evaluate(req, request)
        persist_idempotency_response(request, result)
        return result

    @router.post("/evaluate/review-package")
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

    @router.post("/evaluate/batch")
    def evaluate_batch(req: BatchEvaluateRequest, request: Request) -> dict:
        return {
            "count": len(req.items),
            "results": [_evaluate(item, request) for item in req.items],
        }

    @router.post("/simulation")
    def simulation(req: SimulationRequest) -> dict:
        return evaluation_service.simulate_policy_change(
            baseline_policy_dir=req.baseline_policy_dir,
            candidate_policy_dir=req.candidate_policy_dir,
            scenarios=[item.model_dump() for item in req.scenarios],
        )

    @router.post("/replay/drift")
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

    return router
