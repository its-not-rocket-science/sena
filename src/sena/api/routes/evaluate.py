from __future__ import annotations

from fastapi import APIRouter, Request

from sena.api.errors import raise_api_error
from sena.api.runtime import EngineState, parse_default_decision
from sena.api.schemas import BatchEvaluateRequest, EvaluateRequest, SimulationRequest
from sena.services.audit_service import AuditService
from sena.services.evaluation_service import EvaluationService


def create_evaluate_router(state: EngineState) -> APIRouter:
    router = APIRouter()
    evaluation_service = EvaluationService(state=state, audit_service=AuditService(state.settings.audit_sink_jsonl))

    def _evaluate(req: EvaluateRequest, request: Request) -> dict:
        try:
            proposal = evaluation_service.build_action_proposal(
                action_type=req.action_type,
                request_id=req.request_id or request.state.request_id,
                actor_id=req.actor_id,
                actor_role=req.actor_role,
                attributes=req.attributes,
            )
            return evaluation_service.evaluate(
                proposal=proposal,
                facts=req.facts,
                endpoint="/v1/evaluate",
                default_decision=parse_default_decision(req.default_decision),
                strict_require_allow=req.strict_require_allow,
                notify_on_escalation=True,
                append_audit=True,
            )
        except Exception as exc:  # pragma: no cover
            raise_api_error("evaluation_error", details={"reason": str(exc)})

    @router.post("/evaluate")
    def evaluate(req: EvaluateRequest, request: Request) -> dict:
        return _evaluate(req, request)

    @router.post("/evaluate/review-package")
    def evaluate_review_package(req: EvaluateRequest, request: Request) -> dict:
        try:
            proposal = evaluation_service.build_action_proposal(
                action_type=req.action_type,
                request_id=req.request_id or request.state.request_id,
                actor_id=req.actor_id,
                actor_role=req.actor_role,
                attributes=req.attributes,
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
        return {"count": len(req.items), "results": [_evaluate(item, request) for item in req.items]}

    @router.post("/simulation")
    def simulation(req: SimulationRequest) -> dict:
        return evaluation_service.simulate_policy_change(
            baseline_policy_dir=req.baseline_policy_dir,
            candidate_policy_dir=req.candidate_policy_dir,
            scenarios=[item.model_dump() for item in req.scenarios],
        )

    return router
