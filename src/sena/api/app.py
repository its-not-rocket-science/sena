from __future__ import annotations

import logging
import json
import asyncio
import time
import uuid
from datetime import datetime, timezone
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from sena import __version__ as SENA_VERSION
from sena.audit.chain import append_audit_record, verify_audit_chain
from sena.api.config import ApiSettings, load_settings_from_env
from sena.api.errors import ERROR_CODE_CATALOG, raise_api_error
from sena.api.logging import configure_logging
from sena.api.metrics import ApiMetrics
from sena.api.schemas import (
    BatchEvaluateRequest,
    BundleInfo,
    BundlePromoteRequest,
    BundleRegisterRequest,
    BundleRollbackRequest,
    EvaluateRequest,
    HealthResponse,
    WebhookEvaluateRequest,
    ReadinessResponse,
    SimulationRequest,
)
from sena.core.enums import DecisionOutcome
from sena.core.models import ActionProposal, EvaluatorConfig, PolicyBundleMetadata
from sena.engine.evaluator import PolicyEvaluator
from sena.engine.review_package import build_decision_review_package
from sena.engine.simulation import SimulationScenario, simulate_bundle_impact
from sena.integrations.base import DecisionPayload
from sena.integrations.jira import (
    AllowAllJiraWebhookVerifier,
    JiraConnector,
    JiraIntegrationError,
    SharedSecretJiraWebhookVerifier,
    load_jira_mapping_config,
)
from sena.integrations.registry import build_connector_registry
from sena.integrations.servicenow import (
    ServiceNowConnector,
    ServiceNowIntegrationError,
    load_servicenow_mapping_config,
)
from sena.integrations.webhook import (
    WebhookMappingError,
    WebhookPayloadMapper,
    load_webhook_mapping_config,
)
from sena.integrations.slack import (
    SlackClient,
    SlackIntegrationError,
)
from sena.policy.lifecycle import diff_rule_sets, validate_promotion
from sena.policy.parser import PolicyParseError, load_policy_bundle
from sena.policy.release_signing import verify_release_manifest
from sena.policy.store import SQLitePolicyBundleRepository

try:
    from fastapi import APIRouter, FastAPI, HTTPException, Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse, Response
except ModuleNotFoundError:  # pragma: no cover
    FastAPI = None  # type: ignore


logger = logging.getLogger(__name__)
VALID_API_ROLES = {"admin", "policy_author", "evaluator"}
ROLE_ALLOWED_ENDPOINTS: dict[str, set[tuple[str, str]]] = {
    "policy_author": {
        ("POST", "/v1/bundle/register"),
        ("POST", "/v1/bundle/promote"),
        ("POST", "/v1/bundle/diff"),
        ("POST", "/v1/bundle/promotion/validate"),
        ("POST", "/v1/bundle/rollback"),
        ("GET", "/v1/bundles/history"),
        ("GET", "/v1/bundles/active"),
        ("GET", "/v1/bundles/by-version"),
    },
    "evaluator": {
        ("POST", "/v1/evaluate"),
        ("POST", "/v1/evaluate/review-package"),
        ("POST", "/v1/evaluate/batch"),
        ("POST", "/v1/integrations/webhook"),
        ("POST", "/v1/integrations/jira/webhook"),
        ("POST", "/v1/integrations/servicenow/webhook"),
        ("POST", "/v1/integrations/slack/interactions"),
        ("POST", "/v1/simulation"),
    },
}


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
        self.metrics = ApiMetrics()
        self.webhook_mapper: WebhookPayloadMapper | None = None
        self.slack_client: SlackClient | None = None
        self.connector_registry = build_connector_registry()
        self.jira_connector: JiraConnector | None = None
        self.servicenow_connector: ServiceNowConnector | None = None


def _verify_bundle_signature(
    *,
    policy_dir: str,
    manifest_filename: str,
    keyring_dir: str | None,
    strict: bool,
) -> tuple[bool, list[str], str]:
    manifest_path = Path(policy_dir) / manifest_filename
    if not manifest_path.exists():
        if strict:
            return False, [f"release manifest not found: {manifest_path}"], str(manifest_path)
        return True, [], str(manifest_path)
    result = verify_release_manifest(
        Path(policy_dir),
        manifest_path=manifest_path,
        keyring_dir=Path(keyring_dir) if keyring_dir else None,
        strict=strict,
    )
    return result.valid, result.errors, str(manifest_path)


class _FixedWindowRateLimiter:
    def __init__(self, max_requests: int, window_seconds: int):
        if max_requests <= 0:
            raise ValueError("rate limit requests must be > 0")
        if window_seconds <= 0:
            raise ValueError("rate limit window seconds must be > 0")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._request_windows: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, now: float) -> bool:
        bucket = self._request_windows[key]
        window_start = now - self.window_seconds
        while bucket and bucket[0] <= window_start:
            bucket.popleft()
        if len(bucket) >= self.max_requests:
            return False
        bucket.append(now)
        return True


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
        if not active.rules:
            raise RuntimeError(
                f"Active bundle '{runtime_settings.bundle_name}' in sqlite store has no rules"
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
    if not rules:
        raise RuntimeError(
            f"Loaded bundle '{metadata.bundle_name}' version '{metadata.version}' contains no rules"
        )
    return rules, metadata, None


def _validate_startup_settings(runtime_settings: ApiSettings) -> None:
    if runtime_settings.policy_store_backend == "filesystem":
        policy_dir = Path(runtime_settings.policy_dir)
        if not policy_dir.exists() or not policy_dir.is_dir():
            raise RuntimeError(
                f"SENA_POLICY_DIR must point to an existing directory: {runtime_settings.policy_dir}"
            )

    if runtime_settings.api_key and not runtime_settings.enable_api_key_auth:
        raise RuntimeError("SENA_API_KEY is set but SENA_API_KEY_ENABLED is not true")
    if runtime_settings.runtime_mode == "production" and not runtime_settings.enable_api_key_auth:
        raise RuntimeError("SENA_RUNTIME_MODE=production requires SENA_API_KEY_ENABLED=true")
    if runtime_settings.api_keys and runtime_settings.api_key:
        raise RuntimeError("Set only one of SENA_API_KEY or SENA_API_KEYS")
    if runtime_settings.enable_api_key_auth and not runtime_settings.api_key and not runtime_settings.api_keys:
        raise RuntimeError("SENA_API_KEY_ENABLED=true requires SENA_API_KEY or SENA_API_KEYS to be set")
    for _, role in runtime_settings.api_keys:
        if role not in VALID_API_ROLES:
            raise RuntimeError(
                f"SENA_API_KEYS contains unsupported role '{role}'. Expected one of: {sorted(VALID_API_ROLES)}"
            )


def _build_api_key_roles(settings: ApiSettings) -> dict[str, str]:
    if settings.api_keys:
        return dict(settings.api_keys)
    if settings.api_key:
        return {settings.api_key: "admin"}
    return {}


def _is_role_allowed(role: str, method: str, path: str) -> bool:
    if role == "admin":
        return True
    return (method, path) in ROLE_ALLOWED_ENDPOINTS.get(role, set())


def create_app(settings: ApiSettings | None = None):
    if FastAPI is None:
        raise RuntimeError("FastAPI is not installed. Install optional API dependencies first.")

    runtime_settings = settings or load_settings_from_env()
    configure_logging(runtime_settings.log_level)
    _validate_startup_settings(runtime_settings)

    if runtime_settings.request_max_bytes <= 0:
        raise RuntimeError("SENA_REQUEST_MAX_BYTES must be greater than 0")
    if runtime_settings.request_timeout_seconds <= 0:
        raise RuntimeError("SENA_REQUEST_TIMEOUT_SECONDS must be greater than 0")

    rules, metadata, policy_repo = _load_runtime_bundle(runtime_settings)

    app = FastAPI(title="SENA Compliance Engine API", version=SENA_VERSION)
    state = _EngineState(runtime_settings, rules, metadata, policy_repo)
    api_key_roles = _build_api_key_roles(runtime_settings)
    rate_limiter = _FixedWindowRateLimiter(
        max_requests=runtime_settings.rate_limit_requests,
        window_seconds=runtime_settings.rate_limit_window_seconds,
    )
    if runtime_settings.webhook_mapping_config_path:
        mapping_config = load_webhook_mapping_config(runtime_settings.webhook_mapping_config_path)
        state.webhook_mapper = WebhookPayloadMapper(mapping_config)
    if runtime_settings.slack_bot_token and runtime_settings.slack_channel:
        state.slack_client = SlackClient(
            bot_token=runtime_settings.slack_bot_token,
            default_channel=runtime_settings.slack_channel,
        )
    state.connector_registry = build_connector_registry(
        webhook=state.webhook_mapper,
        slack=state.slack_client,
        jira=state.jira_connector,
        servicenow=state.servicenow_connector,
    )
    if runtime_settings.jira_mapping_config_path:
        verifier = (
            SharedSecretJiraWebhookVerifier(runtime_settings.jira_webhook_secret)
            if runtime_settings.jira_webhook_secret
            else AllowAllJiraWebhookVerifier()
        )
        state.jira_connector = JiraConnector(
            config=load_jira_mapping_config(runtime_settings.jira_mapping_config_path),
            verifier=verifier,
        )
        state.connector_registry = build_connector_registry(
            webhook=state.webhook_mapper,
            slack=state.slack_client,
            jira=state.jira_connector,
            servicenow=state.servicenow_connector,
        )

    if runtime_settings.servicenow_mapping_config_path:
        state.servicenow_connector = ServiceNowConnector(
            config=load_servicenow_mapping_config(runtime_settings.servicenow_mapping_config_path)
        )
        state.connector_registry = build_connector_registry(
            webhook=state.webhook_mapper,
            slack=state.slack_client,
            jira=state.jira_connector,
            servicenow=state.servicenow_connector,
        )

    deprecation_date = "2026-04-01"
    deprecation_message = (
        "Unversioned API routes are deprecated and removed. "
        "Use versioned /v1 routes."
    )
    deprecation_doc_url = "https://github.com/openai/sena#api-versioning-policy"

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or f"req_{uuid.uuid4().hex[:12]}"
        request.state.request_id = request_id
        client_key = request.headers.get("x-api-key", "")
        if not client_key:
            client_host = request.client.host if request.client else "unknown"
            client_key = f"anonymous:{client_host}"

        def _json_error(status_code: int, code: str, message: str) -> JSONResponse:
            error_response = JSONResponse(
                status_code=status_code,
                content=_error_payload(code, message, request_id),
            )
            state.metrics.observe_request(
                method=request.method,
                path=request.url.path,
                status_code=status_code,
            )
            return error_response

        content_length = request.headers.get("content-length")
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError:
                return _json_error(400, "invalid_content_length", "Invalid Content-Length header")
            if declared_size > state.settings.request_max_bytes:
                return _json_error(413, "payload_too_large", "Request payload exceeds maximum size")

        body = await request.body()
        if len(body) > state.settings.request_max_bytes:
            return _json_error(413, "payload_too_large", "Request payload exceeds maximum size")

        async def _receive() -> dict[str, Any]:
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = _receive  # type: ignore[attr-defined]

        if state.settings.enable_api_key_auth:
            provided = request.headers.get("x-api-key")
            role = api_key_roles.get(provided or "")
            if role is None:
                return _json_error(401, "unauthorized", "Missing or invalid API key")
            client_key = provided
            request.state.api_role = role
            if not _is_role_allowed(role, request.method, request.url.path):
                return _json_error(403, "forbidden", "API key role is not authorized for this endpoint")

        if not rate_limiter.allow(client_key, time.monotonic()):
            return _json_error(429, "rate_limited", "Rate limit exceeded")

        try:
            response = await asyncio.wait_for(
                call_next(request), timeout=state.settings.request_timeout_seconds
            )
        except asyncio.TimeoutError:
            return _json_error(504, "timeout", "Request processing timed out")
        response.headers["x-request-id"] = request_id
        state.metrics.observe_request(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
        )
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
        payload = _error_payload(
            "validation_error",
            ERROR_CODE_CATALOG["validation_error"].message,
            request.state.request_id,
        )
        payload["error"]["details"] = exc.errors()
        return JSONResponse(
            status_code=422,
            content=payload,
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        code = detail.get("code", "http_internal_error")
        default_message = ERROR_CODE_CATALOG.get(
            code, ERROR_CODE_CATALOG["http_internal_error"]
        ).message
        message = detail.get("message", default_message)
        payload = _error_payload(code, message, request.state.request_id)
        if "details" in detail:
            payload["error"]["details"] = detail["details"]
        return JSONResponse(
            status_code=exc.status_code,
            content=payload,
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
            raise_api_error("policy_store_unavailable")

        policy_dir = payload.policy_dir or state.settings.policy_dir
        rules, metadata = load_policy_bundle(
            policy_dir,
            bundle_name=payload.bundle_name or state.settings.bundle_name,
            version=payload.bundle_version or state.settings.bundle_version,
        )
        metadata.lifecycle = payload.lifecycle
        signature_ok, signature_errors, manifest_path = _verify_bundle_signature(
            policy_dir=policy_dir,
            manifest_filename=state.settings.bundle_release_manifest_filename,
            keyring_dir=state.settings.bundle_signature_keyring_dir,
            strict=state.settings.bundle_signature_strict,
        )
        if state.settings.bundle_signature_strict and not signature_ok:
            raise_api_error("bundle_signature_verification_failed", details={"errors": signature_errors})
        try:
            bundle_id = state.policy_repo.register_bundle(
                metadata,
                rules,
                created_by=payload.created_by,
                creation_reason=payload.creation_reason,
                source_bundle_id=payload.source_bundle_id,
                compatibility_notes=payload.compatibility_notes,
                release_notes=payload.release_notes,
                migration_notes=payload.migration_notes,
                release_manifest_path=manifest_path,
                signature_verification_strict=state.settings.bundle_signature_strict,
                signature_verified=signature_ok,
                signature_error="; ".join(signature_errors) if signature_errors else None,
            )
        except ValueError as exc:
            raise_api_error("http_bad_request", details={"reason": str(exc)})

        return {
            "bundle_id": bundle_id,
            "bundle": metadata.__dict__,
            "rules_total": len(rules),
            "signature": {"verified": signature_ok, "errors": signature_errors},
        }

    @api_v1.post("/bundle/promote")
    def promote_bundle(payload: BundlePromoteRequest) -> dict[str, Any]:
        if state.policy_repo is None:
            raise_api_error("policy_store_unavailable")

        stored_bundle = state.policy_repo.get_bundle(payload.bundle_id)
        if stored_bundle is None:
            raise_api_error("bundle_not_found", details={"bundle_id": payload.bundle_id})

        source_rules = stored_bundle.rules
        if payload.target_lifecycle == "active":
            current_active = state.policy_repo.get_active_bundle(stored_bundle.metadata.bundle_name)
            source_rules = current_active.rules if current_active is not None else []

        validation = validate_promotion(
            stored_bundle.metadata.lifecycle,
            payload.target_lifecycle,
            source_rules,
            stored_bundle.rules,
            validation_artifact=payload.validation_artifact,
            signature_verified=stored_bundle.signature_verified,
            signature_verification_strict=stored_bundle.signature_verification_strict,
        )
        if not validation.valid:
            raise_api_error("promotion_validation_failed", details={"errors": validation.errors})

        try:
            state.policy_repo.transition_bundle(
                payload.bundle_id,
                payload.target_lifecycle,
                promoted_by=payload.promoted_by,
                promotion_reason=payload.promotion_reason,
                validation_artifact=payload.validation_artifact,
            )
        except ValueError as exc:
            raise_api_error("promotion_validation_failed", details={"errors": [str(exc)]})

        active = state.policy_repo.get_active_bundle(state.settings.bundle_name)
        if active is not None:
            state.rules = active.rules
            state.metadata = active.metadata
        return {"status": "ok", "bundle_id": payload.bundle_id, "lifecycle": payload.target_lifecycle}

    @api_v1.post("/bundle/rollback")
    def rollback_bundle(payload: BundleRollbackRequest) -> dict[str, Any]:
        if state.policy_repo is None:
            raise_api_error("policy_store_unavailable")
        try:
            state.policy_repo.rollback_bundle(
                payload.bundle_name,
                payload.to_bundle_id,
                promoted_by=payload.promoted_by,
                promotion_reason=payload.promotion_reason,
                validation_artifact=payload.validation_artifact,
            )
        except ValueError as exc:
            raise_api_error("promotion_validation_failed", details={"errors": [str(exc)]})

        active = state.policy_repo.get_active_bundle(payload.bundle_name)
        if active is not None and payload.bundle_name == state.settings.bundle_name:
            state.rules = active.rules
            state.metadata = active.metadata

        return {"status": "ok", "bundle_name": payload.bundle_name, "active_bundle_id": payload.to_bundle_id}

    @api_v1.get("/bundles/active")
    def get_active_bundle(bundle_name: str | None = None) -> dict[str, Any]:
        if state.policy_repo is None:
            raise_api_error("policy_store_unavailable")
        name = bundle_name or state.settings.bundle_name
        active = state.policy_repo.get_active_bundle(name)
        if active is None:
            raise_api_error("active_bundle_not_found", details={"bundle_name": name})
        return {
            "bundle_id": active.id,
            "bundle": BundleInfo.model_validate(active.metadata.__dict__),
            "release_id": active.release_id,
            "created_by": active.created_by,
            "promoted_by": active.promoted_by,
            "promotion_reason": active.promotion_reason,
            "validation_artifact": active.validation_artifact,
            "source_bundle_id": active.source_bundle_id,
            "integrity_digest": active.integrity_digest,
            "release_notes": active.release_notes,
            "migration_notes": active.migration_notes,
            "rules_total": len(active.rules),
            "created_at": active.created_at,
        }

    @api_v1.get("/bundles/{bundle_id}")
    def get_bundle_by_id(bundle_id: int) -> dict[str, Any]:
        if state.policy_repo is None:
            raise_api_error("policy_store_unavailable")
        bundle = state.policy_repo.get_bundle(bundle_id)
        if bundle is None:
            raise_api_error("bundle_not_found", details={"bundle_id": bundle_id})
        return {
            "bundle_id": bundle.id,
            "bundle": BundleInfo.model_validate(bundle.metadata.__dict__),
            "release_id": bundle.release_id,
            "created_by": bundle.created_by,
            "creation_reason": bundle.creation_reason,
            "promoted_by": bundle.promoted_by,
            "promotion_reason": bundle.promotion_reason,
            "source_bundle_id": bundle.source_bundle_id,
            "integrity_digest": bundle.integrity_digest,
            "compatibility_notes": bundle.compatibility_notes,
            "release_notes": bundle.release_notes,
            "migration_notes": bundle.migration_notes,
            "validation_artifact": bundle.validation_artifact,
            "rules_total": len(bundle.rules),
            "created_at": bundle.created_at,
        }

    @api_v1.get("/bundles/by-version")
    def get_bundle_by_version(bundle_name: str, version: str) -> dict[str, Any]:
        if state.policy_repo is None:
            raise_api_error("policy_store_unavailable")
        bundle = state.policy_repo.get_bundle_by_version(bundle_name, version)
        if bundle is None:
            raise_api_error("bundle_not_found", details={"bundle_name": bundle_name, "version": version})
        return {
            "bundle_id": bundle.id,
            "bundle": BundleInfo.model_validate(bundle.metadata.__dict__),
            "release_id": bundle.release_id,
            "created_at": bundle.created_at,
        }

    @api_v1.get("/bundles/history")
    def bundle_history(bundle_name: str) -> dict[str, Any]:
        if state.policy_repo is None:
            raise_api_error("policy_store_unavailable")
        return {"bundle_name": bundle_name, "history": state.policy_repo.get_history(bundle_name)}
    @api_v1.post("/evaluate")
    def evaluate(req: EvaluateRequest, request: Request) -> dict[str, Any]:
        try:
            def _notify_slack(trace) -> None:
                if state.slack_client is None:
                    return
                state.slack_client.send_decision(
                    DecisionPayload(
                        decision_id=trace.decision_id,
                        request_id=trace.request_id,
                        action_type=trace.action_type,
                        matched_rule_ids=[item.rule_id for item in trace.matched_rules],
                        summary=trace.summary,
                    )
                )

            proposal = ActionProposal(
                action_type=req.action_type,
                request_id=req.request_id or request.state.request_id,
                actor_id=req.actor_id,
                actor_role=req.actor_role,
                attributes=req.attributes,
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
            with state.metrics.evaluation_timer(endpoint="/v1/evaluate"):
                trace = evaluator.evaluate(proposal, req.facts)
            state.metrics.observe_decision_outcome(endpoint="/v1/evaluate", outcome=trace.outcome.value)
            payload = trace.to_dict()
            if state.settings.audit_sink_jsonl:
                payload["audit_record"] = append_audit_record(
                    state.settings.audit_sink_jsonl, payload["audit_record"]
                )
            return payload
        except Exception as exc:  # pragma: no cover
            raise_api_error("evaluation_error", details={"reason": str(exc)})




    @api_v1.post("/evaluate/review-package")
    def evaluate_review_package(req: EvaluateRequest, request: Request) -> dict[str, Any]:
        try:
            proposal = ActionProposal(
                action_type=req.action_type,
                request_id=req.request_id or request.state.request_id,
                actor_id=req.actor_id,
                actor_role=req.actor_role,
                attributes=req.attributes,
            )
            evaluator = PolicyEvaluator(
                state.rules,
                policy_bundle=state.metadata,
                config=EvaluatorConfig(
                    default_decision=_parse_default_decision(req.default_decision),
                    require_allow_match=req.strict_require_allow,
                ),
            )
            with state.metrics.evaluation_timer(endpoint="/v1/evaluate/review-package"):
                trace = evaluator.evaluate(proposal, req.facts)
            state.metrics.observe_decision_outcome(
                endpoint="/v1/evaluate/review-package",
                outcome=trace.outcome.value,
            )
            return build_decision_review_package(trace)
        except Exception as exc:  # pragma: no cover
            raise_api_error("evaluation_error", details={"reason": str(exc)})

    @api_v1.post("/integrations/webhook")
    def integrations_webhook(req: WebhookEvaluateRequest, request: Request) -> dict[str, Any]:
        if state.webhook_mapper is None:
            raise_api_error("webhook_mapping_not_configured")
        try:
            mapped = state.connector_registry.get("webhook").handle_event(
                {
                    "provider": req.provider,
                    "event_type": req.event_type,
                    "payload": req.payload,
                    "default_request_id": request.state.request_id,
                }
            )
            normalized = mapped["normalized_event"]
            proposal = mapped["action_proposal"]
            evaluator = PolicyEvaluator(
                state.rules,
                policy_bundle=state.metadata,
                config=EvaluatorConfig(
                    default_decision=_parse_default_decision(req.default_decision),
                    require_allow_match=req.strict_require_allow,
                    on_escalation=(
                        lambda trace: state.slack_client.send_decision(
                            DecisionPayload(
                                decision_id=trace.decision_id,
                                request_id=trace.request_id,
                                action_type=trace.action_type,
                                matched_rule_ids=[item.rule_id for item in trace.matched_rules],
                                summary=trace.summary,
                            )
                        )
                        if state.slack_client is not None
                        else None
                    ),
                ),
            )
            with state.metrics.evaluation_timer(endpoint="/v1/integrations/webhook"):
                trace = evaluator.evaluate(proposal, req.facts)
            state.metrics.observe_decision_outcome(
                endpoint="/v1/integrations/webhook",
                outcome=trace.outcome.value,
            )
            return {
                "provider": req.provider,
                "event_type": req.event_type,
                "normalized_event": normalized,
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
            raise_api_error("webhook_mapping_error", details={"reason": str(exc)})
        except Exception as exc:  # pragma: no cover
            raise_api_error("webhook_evaluation_error", details={"reason": str(exc)})

    @api_v1.post("/integrations/jira/webhook")
    async def integrations_jira_webhook(request: Request) -> dict[str, Any]:
        if state.jira_connector is None:
            raise_api_error("jira_mapping_not_configured")
        raw_body = await request.body()
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            raise_api_error("validation_error", details={"reason": "Malformed JSON body"})

        try:
            mapped = state.connector_registry.get("jira").handle_event(
                {
                    "headers": dict(request.headers.items()),
                    "payload": payload,
                    "raw_body": raw_body,
                }
            )
            normalized = mapped["normalized_event"]
            proposal = mapped["action_proposal"]
            event_route = state.jira_connector.route_for_event_type(normalized["source_event_type"])
            if event_route and event_route.policy_bundle and event_route.policy_bundle != state.metadata.bundle_name:
                raise_api_error(
                    "jira_policy_bundle_not_found",
                    details={
                        "required_bundle": event_route.policy_bundle,
                        "loaded_bundle": state.metadata.bundle_name,
                    },
                )
            evaluator = PolicyEvaluator(
                state.rules,
                policy_bundle=state.metadata,
                config=EvaluatorConfig(default_decision=DecisionOutcome.APPROVED),
            )
            with state.metrics.evaluation_timer(endpoint="/v1/integrations/jira/webhook"):
                trace = evaluator.evaluate(proposal, {})
            outbound = state.jira_connector.send_decision(
                DecisionPayload(
                    decision_id=trace.decision_id,
                    request_id=proposal.request_id,
                    action_type=proposal.action_type,
                    matched_rule_ids=[item.rule_id for item in trace.matched_rules],
                    summary=trace.summary,
                )
            )
            return {
                "status": "evaluated",
                "normalized_event": normalized,
                "mapped_action_proposal": {
                    "action_type": proposal.action_type,
                    "request_id": proposal.request_id,
                    "actor_id": proposal.actor_id,
                    "attributes": proposal.attributes,
                },
                "decision": trace.to_dict(),
                "outbound_delivery": outbound,
            }
        except JiraIntegrationError as exc:
            reason = str(exc)
            if "duplicate delivery" in reason:
                return {
                    "status": "duplicate_ignored",
                    "error": {"code": "jira_duplicate_delivery", "message": reason},
                }
            if "unsupported jira event type" in reason:
                raise_api_error("jira_unsupported_event_type", details={"reason": reason})
            if "missing required fields" in reason or "missing actor identity" in reason:
                raise_api_error("jira_missing_required_fields", details={"reason": reason})
            if "signature" in reason:
                raise_api_error("jira_authentication_failed", details={"reason": reason})
            raise_api_error("jira_invalid_mapping", details={"reason": reason})
        except Exception as exc:  # pragma: no cover
            raise_api_error("jira_evaluation_error", details={"reason": str(exc)})

    @api_v1.post("/integrations/servicenow/webhook")
    async def integrations_servicenow_webhook(
        request: Request,
        strict_require_allow: bool = False,
    ) -> dict[str, Any]:
        if state.servicenow_connector is None:
            raise_api_error("servicenow_mapping_not_configured")
        raw_body = await request.body()
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            raise_api_error("validation_error", details={"reason": "Malformed JSON body"})

        try:
            mapped = state.connector_registry.get("servicenow").handle_event(
                {
                    "headers": dict(request.headers.items()),
                    "payload": payload,
                    "raw_body": raw_body,
                }
            )
            normalized = mapped["normalized_event"]
            proposal = mapped["action_proposal"]
            event_route = state.servicenow_connector.route_for_event_type(normalized["source_event_type"])
            if event_route and event_route.policy_bundle and event_route.policy_bundle != state.metadata.bundle_name:
                raise_api_error(
                    "servicenow_policy_bundle_not_found",
                    details={
                        "required_bundle": event_route.policy_bundle,
                        "loaded_bundle": state.metadata.bundle_name,
                    },
                )

            evaluator = PolicyEvaluator(
                state.rules,
                policy_bundle=state.metadata,
                config=EvaluatorConfig(
                    default_decision=DecisionOutcome.APPROVED,
                    require_allow_match=strict_require_allow,
                ),
            )
            with state.metrics.evaluation_timer(endpoint="/v1/integrations/servicenow/webhook"):
                trace = evaluator.evaluate(proposal, {})
            outbound = state.servicenow_connector.send_decision(
                DecisionPayload(
                    decision_id=trace.decision_id,
                    request_id=proposal.request_id,
                    action_type=proposal.action_type,
                    matched_rule_ids=[item.rule_id for item in trace.matched_rules],
                    summary=trace.summary,
                )
            )
            return {
                "status": "evaluated",
                "normalized_event": normalized,
                "mapped_action_proposal": {
                    "action_type": proposal.action_type,
                    "request_id": proposal.request_id,
                    "actor_id": proposal.actor_id,
                    "actor_role": proposal.actor_role,
                    "attributes": proposal.attributes,
                },
                "decision": trace.to_dict(),
                "outbound_delivery": outbound,
            }
        except ServiceNowIntegrationError as exc:
            reason = str(exc)
            if "duplicate delivery" in reason:
                return {
                    "status": "duplicate_ignored",
                    "error": {"code": "servicenow_duplicate_delivery", "message": reason},
                }
            if "unsupported servicenow event type" in reason:
                raise_api_error("servicenow_unsupported_event_type", details={"reason": reason})
            if "missing required fields" in reason or "missing actor identity" in reason:
                raise_api_error("servicenow_missing_required_fields", details={"reason": reason})
            raise_api_error("servicenow_invalid_mapping", details={"reason": reason})
        except Exception as exc:  # pragma: no cover
            raise_api_error("servicenow_evaluation_error", details={"reason": str(exc)})

    @api_v1.post("/integrations/slack/interactions")
    async def slack_interactions(request: Request) -> dict[str, Any]:
        try:
            form_data = await request.form()
            payload_json = form_data.get("payload")
            if not isinstance(payload_json, str):
                raise SlackIntegrationError("Slack interaction payload form field is required")
            interaction = state.connector_registry.get("slack").handle_event(json.loads(payload_json))
            return {
                "status": "ok",
                "decision": interaction["decision"],
                "decision_id": interaction["decision_id"],
                "reviewer": interaction["reviewer"],
            }
        except SlackIntegrationError as exc:
            raise_api_error("slack_interaction_error", details={"reason": str(exc)})
        except Exception as exc:  # pragma: no cover
            raise_api_error("slack_interaction_error", details={"reason": str(exc)})

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
                source_system=item.source_system,
                workflow_stage=item.workflow_stage,
                risk_category=item.risk_category,
            )
            for item in req.scenarios
        }
        return simulate_bundle_impact(
            scenarios, baseline_rules, candidate_rules, baseline_meta, candidate_meta
        )

    @api_v1.post("/bundle/diff")
    def bundle_diff(payload: dict[str, Any]) -> dict[str, Any]:
        if state.policy_repo and payload.get("current_bundle_id") and payload.get("target_bundle_id"):
            current_bundle = state.policy_repo.get_bundle(int(payload["current_bundle_id"]))
            target_bundle = state.policy_repo.get_bundle(int(payload["target_bundle_id"]))
            if current_bundle is None or target_bundle is None:
                raise_api_error("bundle_not_found")
            return diff_rule_sets(current_bundle.rules, target_bundle.rules).__dict__

        current_rules, _ = load_policy_bundle(payload["current_policy_dir"])
        target_rules, _ = load_policy_bundle(payload["target_policy_dir"])
        return diff_rule_sets(current_rules, target_rules).__dict__

    @api_v1.post("/bundle/promotion/validate")
    def bundle_promotion_validate(payload: dict[str, Any]) -> dict[str, Any]:
        if state.policy_repo and payload.get("bundle_id"):
            bundle = state.policy_repo.get_bundle(int(payload["bundle_id"]))
            if bundle is None:
                raise_api_error("bundle_not_found")
            source_rules = bundle.rules
            if payload.get("target_lifecycle") == "active":
                active = state.policy_repo.get_active_bundle(bundle.metadata.bundle_name)
                source_rules = active.rules if active else []
            result = validate_promotion(
                bundle.metadata.lifecycle,
                payload["target_lifecycle"],
                source_rules,
                bundle.rules,
                validation_artifact=payload.get("validation_artifact"),
                signature_verified=bundle.signature_verified,
                signature_verification_strict=bundle.signature_verification_strict,
            )
            return result.__dict__

        source_rules, source_meta = load_policy_bundle(payload["source_policy_dir"])
        target_rules, target_meta = load_policy_bundle(payload["target_policy_dir"])
        signature_verified = True
        signature_strict = bool(payload.get("signature_strict", False))
        if signature_strict:
            manifest_name = payload.get("manifest_filename", state.settings.bundle_release_manifest_filename)
            verified, errors, _ = _verify_bundle_signature(
                policy_dir=payload["target_policy_dir"],
                manifest_filename=manifest_name,
                keyring_dir=payload.get("keyring_dir") or state.settings.bundle_signature_keyring_dir,
                strict=True,
            )
            signature_verified = verified
            if errors and not verified:
                logger.warning("bundle promotion validation signature errors: %s", errors)
        result = validate_promotion(
            payload.get("source_lifecycle", source_meta.lifecycle),
            payload.get("target_lifecycle", target_meta.lifecycle),
            source_rules,
            target_rules,
            validation_artifact=payload.get("validation_artifact"),
            signature_verified=signature_verified,
            signature_verification_strict=signature_strict,
        )
        return result.__dict__

    @api_v1.get("/audit/verify")
    def audit_verify() -> dict[str, Any]:
        if not state.settings.audit_sink_jsonl:
            raise_api_error("audit_sink_not_configured")
        return verify_audit_chain(state.settings.audit_sink_jsonl)

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(content=state.metrics.exposition(), media_type=state.metrics.content_type)

    app.include_router(api_v1)

    def _deprecated_unversioned_response(versioned_path: str) -> JSONResponse:
        response = JSONResponse(
            status_code=410,
            content=_error_payload(
                "route_deprecated",
                f"{deprecation_message} Migrate to '{versioned_path}'.",
            ),
        )
        response.headers["Deprecation"] = "true"
        response.headers["Sunset"] = deprecation_date
        response.headers["Warning"] = (
            f'299 - "{deprecation_message} Migrate to {versioned_path}."'
        )
        response.headers["Link"] = f'<{deprecation_doc_url}>; rel="deprecation"'
        return response

    @app.get("/health")
    def health_unversioned_deprecated() -> JSONResponse:
        return _deprecated_unversioned_response("/v1/health")

    @app.get("/bundle")
    def bundle_unversioned_deprecated() -> JSONResponse:
        return _deprecated_unversioned_response("/v1/bundle")

    @app.post("/evaluate")
    def evaluate_unversioned_deprecated() -> JSONResponse:
        return _deprecated_unversioned_response("/v1/evaluate")

    return app


app = create_app() if FastAPI is not None else None
