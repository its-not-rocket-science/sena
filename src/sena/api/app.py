from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sena import __version__ as SENA_VERSION
from sena.audit.chain import append_audit_record, verify_audit_chain
from sena.api.config import ApiSettings, load_settings_from_env
from sena.api.logging import configure_logging
from sena.api.schemas import (
    BatchEvaluateRequest,
    BundleInfo,
    EvaluateRequest,
    HealthResponse,
    ReadinessResponse,
    SimulationRequest,
)
from sena.core.enums import DecisionOutcome
from sena.core.models import ActionProposal, EvaluatorConfig, PolicyBundleMetadata
from sena.engine.evaluator import PolicyEvaluator
from sena.engine.simulation import SimulationScenario, simulate_bundle_impact
from sena.policy.parser import PolicyParseError, load_policy_bundle
from sena.policy.lifecycle import diff_rule_sets, validate_promotion

try:
    from fastapi import APIRouter, FastAPI, HTTPException, Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
except ModuleNotFoundError:  # pragma: no cover
    FastAPI = None  # type: ignore


logger = logging.getLogger(__name__)


def _error_payload(code: str, message: str, request_id: str | None = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    }


class _EngineState:
    def __init__(self, settings: ApiSettings, rules: list, metadata: PolicyBundleMetadata):
        self.settings = settings
        self.rules = rules
        self.metadata = metadata



def _parse_default_decision(raw: str) -> DecisionOutcome:
    if raw == "ESCALATE":
        return DecisionOutcome.ESCALATE_FOR_HUMAN_REVIEW
    return DecisionOutcome(raw)



def create_app(settings: ApiSettings | None = None):
    if FastAPI is None:
        raise RuntimeError("FastAPI is not installed. Install optional API dependencies first.")

    runtime_settings = settings or load_settings_from_env()
    configure_logging(runtime_settings.log_level)

    if runtime_settings.enable_api_key_auth and not runtime_settings.api_key:
        raise RuntimeError("SENA_API_KEY_ENABLED=true requires SENA_API_KEY to be set")

    try:
        rules, metadata = load_policy_bundle(
            runtime_settings.policy_dir,
            bundle_name=runtime_settings.bundle_name,
            version=runtime_settings.bundle_version,
        )
    except PolicyParseError as exc:
        raise RuntimeError(f"Failed to load policy bundle: {exc}") from exc

    app = FastAPI(title="SENA Compliance Engine API", version=SENA_VERSION)
    state = _EngineState(runtime_settings, rules, metadata)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or f"req_{uuid.uuid4().hex[:12]}"
        request.state.request_id = request_id

        if state.settings.enable_api_key_auth:
            provided = request.headers.get("x-api-key")
            if provided != state.settings.api_key:
                return JSONResponse(
                    status_code=401,
                    content=_error_payload("unauthorized", "Missing or invalid API key", request_id),
                )

        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        logger.info(
            "request_processed",
            extra={
                "request_id": request_id,
                "path": request.url.path,
                "method": request.method,
                "status_code": response.status_code,
            },
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=_error_payload("validation_error", str(exc), request.state.request_id),
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload("http_error", str(exc.detail), request.state.request_id),
        )

    api_v1 = APIRouter(prefix="/v1")

    @api_v1.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", bundle=BundleInfo.model_validate(state.metadata.__dict__))

    @api_v1.get("/ready", response_model=ReadinessResponse)
    def ready() -> ReadinessResponse:
        return ReadinessResponse(status="ready", checks={"policy_bundle_loaded": "ok"})

    @api_v1.get("/bundle", response_model=BundleInfo)
    def bundle() -> BundleInfo:
        return BundleInfo.model_validate(state.metadata.__dict__)

    @api_v1.get("/bundle/inspect")
    def bundle_inspect() -> dict[str, Any]:
        applies_to: dict[str, int] = {}
        for rule in state.rules:
            for action in rule.applies_to:
                applies_to[action] = applies_to.get(action, 0) + 1
        return {
            "bundle": BundleInfo.model_validate(state.metadata.__dict__),
            "rules_total": len(state.rules),
            "actions_covered": applies_to,
        }

    @api_v1.post("/evaluate")
    def evaluate(req: EvaluateRequest, request: Request) -> dict[str, Any]:
        try:
            proposal = ActionProposal(
                action_type=req.action_type,
                request_id=req.request_id or request.state.request_id,
                actor_id=req.actor_id,
                attributes={**req.attributes, "actor_role": req.actor_role},
            )
            evaluator = PolicyEvaluator(
                state.rules,
                policy_bundle=state.metadata,
                config=EvaluatorConfig(
                    default_decision=_parse_default_decision(req.default_decision),
                    require_allow_match=req.strict_require_allow,
                ),
            )
            trace = evaluator.evaluate(proposal, req.facts)
            payload = trace.to_dict()
            if state.settings.audit_sink_jsonl:
                payload["audit_record"] = append_audit_record(
                    state.settings.audit_sink_jsonl, payload["audit_record"]
                )
            return payload
        except Exception as exc:  # pragma: no cover
            raise HTTPException(status_code=400, detail=f"Evaluation error: {exc}") from exc

    @api_v1.post("/evaluate/batch")
    def evaluate_batch(req: BatchEvaluateRequest, request: Request) -> dict[str, Any]:
        return {
            "count": len(req.items),
            "results": [evaluate(item, request) for item in req.items],
        }

    @api_v1.post("/simulation")
    def simulation(req: SimulationRequest) -> dict[str, Any]:
        baseline_rules, baseline_meta = load_policy_bundle(req.baseline_policy_dir)
        candidate_rules, candidate_meta = load_policy_bundle(req.candidate_policy_dir)
        scenarios = {
            item.scenario_id: SimulationScenario(
                action_type=item.action_type,
                request_id=item.request_id,
                actor_id=item.actor_id,
                attributes=item.attributes,
                facts=item.facts,
            )
            for item in req.scenarios
        }
        return simulate_bundle_impact(
            scenarios, baseline_rules, candidate_rules, baseline_meta, candidate_meta
        )

    @api_v1.post("/bundle/diff")
    def bundle_diff(payload: dict[str, str]) -> dict[str, Any]:
        current_rules, _ = load_policy_bundle(payload["current_policy_dir"])
        target_rules, _ = load_policy_bundle(payload["target_policy_dir"])
        return diff_rule_sets(current_rules, target_rules).__dict__

    @api_v1.post("/bundle/promotion/validate")
    def bundle_promotion_validate(payload: dict[str, Any]) -> dict[str, Any]:
        source_rules, source_meta = load_policy_bundle(payload["source_policy_dir"])
        target_rules, target_meta = load_policy_bundle(payload["target_policy_dir"])
        result = validate_promotion(
            payload.get("source_lifecycle", source_meta.lifecycle),
            payload.get("target_lifecycle", target_meta.lifecycle),
            source_rules,
            target_rules,
        )
        return result.__dict__

    @api_v1.get("/audit/verify")
    def audit_verify() -> dict[str, Any]:
        if not state.settings.audit_sink_jsonl:
            raise HTTPException(status_code=400, detail="audit sink not configured")
        return verify_audit_chain(state.settings.audit_sink_jsonl)

    app.include_router(api_v1)

    # Backward-compatible unversioned aliases.
    app.add_api_route("/health", health, methods=["GET"], response_model=HealthResponse)
    app.add_api_route("/bundle", bundle, methods=["GET"], response_model=BundleInfo)
    app.add_api_route("/evaluate", evaluate, methods=["POST"])

    return app


app = create_app() if FastAPI is not None else None
