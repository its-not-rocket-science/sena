from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sena.api.config import ApiSettings, load_settings_from_env
from sena.api.logging import configure_logging
from sena.api.schemas import BundleInfo, EvaluateRequest, HealthResponse, ReadinessResponse
from sena.core.enums import DecisionOutcome
from sena.core.models import ActionProposal, EvaluatorConfig, PolicyBundleMetadata
from sena.engine.evaluator import PolicyEvaluator
from sena.policy.parser import PolicyParseError, load_policy_bundle

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



def _write_audit_sink(path: str, payload: dict[str, Any]) -> None:
    sink = Path(path)
    sink.parent.mkdir(parents=True, exist_ok=True)
    with sink.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, default=str, separators=(",", ":")) + "\n")



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

    app = FastAPI(title="SENA Compliance Engine API", version="0.3.0")
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
                _write_audit_sink(state.settings.audit_sink_jsonl, payload["audit_record"])
            return payload
        except Exception as exc:  # pragma: no cover
            raise HTTPException(status_code=400, detail=f"Evaluation error: {exc}") from exc

    app.include_router(api_v1)

    # Backward-compatible unversioned aliases.
    app.add_api_route("/health", health, methods=["GET"], response_model=HealthResponse)
    app.add_api_route("/bundle", bundle, methods=["GET"], response_model=BundleInfo)
    app.add_api_route("/evaluate", evaluate, methods=["POST"])

    return app


app = create_app() if FastAPI is not None else None
