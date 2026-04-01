from __future__ import annotations

import logging
import json
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
    BundlePromoteRequest,
    BundleRegisterRequest,
    EvaluateRequest,
    HealthResponse,
    WebhookEvaluateRequest,
    ReadinessResponse,
    SimulationRequest,
)
from sena.core.enums import DecisionOutcome
from sena.core.models import ActionProposal, EvaluatorConfig, PolicyBundleMetadata
from sena.engine.evaluator import PolicyEvaluator
from sena.engine.simulation import SimulationScenario, simulate_bundle_impact
from sena.integrations.webhook import (
    WebhookMappingError,
    WebhookPayloadMapper,
    load_webhook_mapping_config,
)
from sena.integrations.slack import (
    SlackClient,
    SlackIntegrationError,
    parse_interaction_decision,
)
from sena.policy.lifecycle import diff_rule_sets, validate_promotion
from sena.policy.parser import PolicyParseError, load_policy_bundle
from sena.policy.store import SQLitePolicyBundleRepository

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
    def __init__(
        self,
        settings: ApiSettings,
        rules: list,
        metadata: PolicyBundleMetadata,
        policy_repo: SQLitePolicyBundleRepository | None,
    ):
        self.settings = settings
        self.rules = rules
        self.metadata = metadata
        self.policy_repo = policy_repo
        self.webhook_mapper: WebhookPayloadMapper | None = None
        self.slack_client: SlackClient | None = None


def _parse_default_decision(raw: str) -> DecisionOutcome:
    if raw == "ESCALATE":
        return DecisionOutcome.ESCALATE_FOR_HUMAN_REVIEW
    return DecisionOutcome(raw)


def _load_runtime_bundle(
    runtime_settings: ApiSettings,
) -> tuple[list, PolicyBundleMetadata, SQLitePolicyBundleRepository | None]:
    if runtime_settings.policy_store_backend == "sqlite":
        if not runtime_settings.policy_store_sqlite_path:
            raise RuntimeError(
                "SENA_POLICY_STORE_SQLITE_PATH is required when SENA_POLICY_STORE_BACKEND=sqlite"
            )
        repo = SQLitePolicyBundleRepository(runtime_settings.policy_store_sqlite_path)
        repo.initialize()
        active = repo.get_active_bundle(runtime_settings.bundle_name)
        if active is None:
            raise RuntimeError(
                f"No active bundle found for '{runtime_settings.bundle_name}' in sqlite store"
            )
        return active.rules, active.metadata, repo

    try:
        rules, metadata = load_policy_bundle(
            runtime_settings.policy_dir,
            bundle_name=runtime_settings.bundle_name,
            version=runtime_settings.bundle_version,
        )
    except PolicyParseError as exc:
        raise RuntimeError(f"Failed to load policy bundle: {exc}") from exc
    return rules, metadata, None


def create_app(settings: ApiSettings | None = None):
    if FastAPI is None:
        raise RuntimeError("FastAPI is not installed. Install optional API dependencies first.")

    runtime_settings = settings or load_settings_from_env()
    configure_logging(runtime_settings.log_level)

    if runtime_settings.enable_api_key_auth and not runtime_settings.api_key:
        raise RuntimeError("SENA_API_KEY_ENABLED=true requires SENA_API_KEY to be set")

    rules, metadata, policy_repo = _load_runtime_bundle(runtime_settings)

    app = FastAPI(title="SENA Compliance Engine API", version=SENA_VERSION)
    state = _EngineState(runtime_settings, rules, metadata, policy_repo)
    if runtime_settings.webhook_mapping_config_path:
        mapping_config = load_webhook_mapping_config(runtime_settings.webhook_mapping_config_path)
        state.webhook_mapper = WebhookPayloadMapper(mapping_config)
    if runtime_settings.slack_bot_token and runtime_settings.slack_channel:
        state.slack_client = SlackClient(
            bot_token=runtime_settings.slack_bot_token,
            default_channel=runtime_settings.slack_channel,
        )

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

    @api_v1.post("/bundle/register")
    def register_bundle(payload: BundleRegisterRequest) -> dict[str, Any]:
        if state.policy_repo is None:
            raise HTTPException(status_code=400, detail="policy store backend is not sqlite")

        policy_dir = payload.policy_dir or state.settings.policy_dir
        rules, metadata = load_policy_bundle(
            policy_dir,
            bundle_name=payload.bundle_name or state.settings.bundle_name,
            version=payload.bundle_version or state.settings.bundle_version,
        )
        metadata.lifecycle = payload.lifecycle
        bundle_id = state.policy_repo.register_bundle(metadata, rules)
        return {"bundle_id": bundle_id, "bundle": metadata.__dict__, "rules_total": len(rules)}

    @api_v1.post("/bundle/promote")
    def promote_bundle(payload: BundlePromoteRequest) -> dict[str, Any]:
        if state.policy_repo is None:
            raise HTTPException(status_code=400, detail="policy store backend is not sqlite")

        stored_bundle = state.policy_repo.get_bundle(payload.bundle_id)
        if stored_bundle is None:
            raise HTTPException(status_code=404, detail=f"bundle id '{payload.bundle_id}' not found")

        source_rules = stored_bundle.rules
        if payload.target_lifecycle == "active":
            current_active = state.policy_repo.get_active_bundle(stored_bundle.metadata.bundle_name)
            source_rules = current_active.rules if current_active is not None else []

        validation = validate_promotion(
            stored_bundle.metadata.lifecycle,
            payload.target_lifecycle,
            source_rules,
            stored_bundle.rules,
        )
        if not validation.valid:
            raise HTTPException(status_code=400, detail={"errors": validation.errors})

        state.policy_repo.set_bundle_lifecycle(payload.bundle_id, payload.target_lifecycle)
        active = state.policy_repo.get_active_bundle(state.settings.bundle_name)
        if active is not None:
            state.rules = active.rules
            state.metadata = active.metadata
        return {"status": "ok", "bundle_id": payload.bundle_id, "lifecycle": payload.target_lifecycle}

    @api_v1.get("/bundles/active")
    def get_active_bundle(bundle_name: str | None = None) -> dict[str, Any]:
        if state.policy_repo is None:
            raise HTTPException(status_code=400, detail="policy store backend is not sqlite")
        name = bundle_name or state.settings.bundle_name
        active = state.policy_repo.get_active_bundle(name)
        if active is None:
            raise HTTPException(status_code=404, detail=f"No active bundle found for '{name}'")
        return {
            "bundle_id": active.id,
            "bundle": BundleInfo.model_validate(active.metadata.__dict__),
            "rules_total": len(active.rules),
            "created_at": active.created_at,
        }

    @api_v1.post("/evaluate")
    def evaluate(req: EvaluateRequest, request: Request) -> dict[str, Any]:
        try:
            def _notify_slack(trace) -> None:
                if state.slack_client is None:
                    return
                state.slack_client.post_escalation(
                    decision_id=trace.decision_id,
                    request_id=trace.request_id,
                    action_type=trace.action_type,
                    matched_rule_ids=[item.rule_id for item in trace.matched_rules],
                    summary=trace.summary,
                )

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
                    on_escalation=_notify_slack,
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


    @api_v1.post("/integrations/webhook")
    def integrations_webhook(req: WebhookEvaluateRequest, request: Request) -> dict[str, Any]:
        if state.webhook_mapper is None:
            raise HTTPException(status_code=400, detail="webhook mapping config is not set")
        try:
            proposal = state.webhook_mapper.map_payload(
                provider=req.provider,
                event_type=req.event_type,
                payload=req.payload,
                default_request_id=request.state.request_id,
            )
            evaluator = PolicyEvaluator(
                state.rules,
                policy_bundle=state.metadata,
                config=EvaluatorConfig(
                    default_decision=_parse_default_decision(req.default_decision),
                    require_allow_match=req.strict_require_allow,
                    on_escalation=(
                        lambda trace: state.slack_client.post_escalation(
                            decision_id=trace.decision_id,
                            request_id=trace.request_id,
                            action_type=trace.action_type,
                            matched_rule_ids=[item.rule_id for item in trace.matched_rules],
                            summary=trace.summary,
                        )
                        if state.slack_client is not None
                        else None
                    ),
                ),
            )
            trace = evaluator.evaluate(proposal, req.facts)
            return {
                "provider": req.provider,
                "event_type": req.event_type,
                "mapped_action_proposal": {
                    "action_type": proposal.action_type,
                    "request_id": proposal.request_id,
                    "actor_id": proposal.actor_id,
                    "attributes": proposal.attributes,
                },
                "decision": trace.to_dict(),
                "reasoning": trace.reasoning.__dict__ if trace.reasoning else None,
            }
        except WebhookMappingError as exc:
            raise HTTPException(status_code=400, detail=f"Webhook mapping error: {exc}") from exc
        except Exception as exc:  # pragma: no cover
            raise HTTPException(status_code=400, detail=f"Webhook evaluation error: {exc}") from exc

    @api_v1.post("/integrations/slack/interactions")
    async def slack_interactions(request: Request) -> dict[str, Any]:
        try:
            form_data = await request.form()
            payload_json = form_data.get("payload")
            if not isinstance(payload_json, str):
                raise SlackIntegrationError("Slack interaction payload form field is required")
            interaction = parse_interaction_decision(payload=json.loads(payload_json))
            return {
                "status": "ok",
                "decision": interaction["decision"],
                "decision_id": interaction["decision_id"],
                "reviewer": interaction["reviewer"],
            }
        except SlackIntegrationError as exc:
            raise HTTPException(status_code=400, detail=f"Slack interaction error: {exc}") from exc
        except Exception as exc:  # pragma: no cover
            raise HTTPException(status_code=400, detail=f"Slack interaction error: {exc}") from exc

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

    app.add_api_route("/health", health, methods=["GET"], response_model=HealthResponse)
    app.add_api_route("/bundle", bundle, methods=["GET"], response_model=BundleInfo)
    app.add_api_route("/evaluate", evaluate, methods=["POST"])

    return app


app = create_app() if FastAPI is not None else None
