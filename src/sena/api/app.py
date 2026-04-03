from __future__ import annotations

from typing import Any, Callable

from sena import __version__ as SENA_VERSION
from sena.audit.chain import verify_audit_chain
from sena.api.config import ApiSettings, load_settings_from_env
from sena.api.error_handlers import error_payload, register_error_handlers
from sena.api.logging import configure_logging
from sena.api.middleware import FixedWindowRateLimiter, register_request_middleware
from sena.api.routes.bundles import create_bundles_router
from sena.api.routes.evaluate import create_evaluate_router
from sena.api.routes.health import create_health_router
from sena.api.routes.integrations import create_integrations_router
from sena.api.schemas import AuditTreeVerifyRequest
from sena.services.audit_service import AuditService
from sena.api.runtime import (
    build_api_key_roles,
    build_runtime_state,
    load_runtime_bundle,
    validate_startup_settings,
)

try:
    from fastapi import APIRouter, FastAPI
    from fastapi.responses import JSONResponse, Response
except ModuleNotFoundError:  # pragma: no cover
    FastAPI = None  # type: ignore


def _validate_runtime_limits(settings: ApiSettings) -> None:
    if settings.request_max_bytes <= 0:
        raise RuntimeError("SENA_REQUEST_MAX_BYTES must be greater than 0")
    if settings.request_timeout_seconds <= 0:
        raise RuntimeError("SENA_REQUEST_TIMEOUT_SECONDS must be greater than 0")


def initialize_runtime(settings: ApiSettings):
    """Validate settings and build runtime dependencies.

    This keeps runtime initialization explicit and testable, while allowing
    app object construction to remain separate.
    """
    configure_logging(settings.log_level)
    validate_startup_settings(settings)
    _validate_runtime_limits(settings)

    rules, metadata, policy_repo = load_runtime_bundle(settings)
    if settings.audit_verify_on_startup_strict and settings.audit_sink_jsonl:
        verification = verify_audit_chain(settings.audit_sink_jsonl)
        if not verification.get("valid", False):
            detail = "; ".join(verification.get("errors", [])) or verification.get(
                "error", "unknown error"
            )
            raise RuntimeError(
                f"Startup audit verification failed for {settings.audit_sink_jsonl}: {detail}"
            )

    return build_runtime_state(settings, rules, metadata, policy_repo)


def build_app(state):
    if FastAPI is None:
        raise RuntimeError(
            "FastAPI is not installed. Install optional API dependencies first."
        )

    app = FastAPI(title="SENA Compliance Engine API", version=SENA_VERSION)
    app.state.engine_state = state

    api_key_roles = build_api_key_roles(state.settings)
    rate_limiter = FixedWindowRateLimiter(
        max_requests=state.settings.rate_limit_requests,
        window_seconds=state.settings.rate_limit_window_seconds,
    )
    register_request_middleware(
        app,
        state=state,
        api_key_roles=api_key_roles,
        rate_limiter=rate_limiter,
    )
    register_error_handlers(app)

    api_v1 = APIRouter(prefix="/v1")
    api_v1.include_router(create_health_router(state))
    api_v1.include_router(create_evaluate_router(state))
    api_v1.include_router(create_bundles_router(state))
    api_v1.include_router(create_integrations_router(state))

    @api_v1.get("/audit/verify")
    def audit_verify() -> dict:
        if not state.settings.audit_sink_jsonl:
            from sena.api.errors import raise_api_error

            raise_api_error("audit_sink_not_configured")
        return verify_audit_chain(state.settings.audit_sink_jsonl)

    @api_v1.post("/audit/verify/tree")
    def audit_verify_tree(req: AuditTreeVerifyRequest) -> dict:
        if not state.settings.audit_sink_jsonl:
            from sena.api.errors import raise_api_error

            raise_api_error("audit_sink_not_configured")

        audit_service = AuditService(state.settings.audit_sink_jsonl)
        result = audit_service.verify_decision_merkle_proof(
            decision_id=req.decision_id,
            merkle_proof=req.merkle_proof,
            expected_root=req.expected_root,
        )
        state.metrics.observe_verification_result(valid=result.get("valid", False))
        return result

    @api_v1.get("/metrics/prometheus")
    def metrics_prometheus() -> Response:
        return Response(
            content=state.metrics.exposition(), media_type=state.metrics.content_type
        )

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(
            content=state.metrics.exposition(), media_type=state.metrics.content_type
        )

    app.include_router(api_v1)

    deprecation_date = "2026-04-01"
    deprecation_message = (
        "Unversioned API routes are deprecated and removed. Use versioned /v1 routes."
    )
    deprecation_doc_url = (
        "https://github.com/its-not-rocket-science/sena#api-versioning-policy"
    )

    def _deprecated_unversioned_response(versioned_path: str) -> JSONResponse:
        response = JSONResponse(
            status_code=410,
            content=error_payload(
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


def create_app(settings: ApiSettings | None = None):
    runtime_settings = settings or load_settings_from_env()
    state = initialize_runtime(runtime_settings)
    return build_app(state)


class _LazyASGIApp:
    """ASGI wrapper that defers create_app() until first call.

    Keeps module import lightweight for tests and tooling.
    """

    def __init__(self, factory: Callable[[], Any]):
        self._factory = factory
        self._app: Any | None = None

    def _get_app(self):
        if self._app is None:
            self._app = self._factory()
        return self._app

    async def __call__(self, scope, receive, send) -> None:
        app = self._get_app()
        await app(scope, receive, send)


app = _LazyASGIApp(create_app) if FastAPI is not None else None
