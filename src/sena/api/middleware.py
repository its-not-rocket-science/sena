from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict, deque
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from sena.api.error_handlers import error_payload
from sena.api.logging import bind_request_context, clear_request_context, get_logger
from sena.api.auth import (
    AuthError,
    AuthManager,
    evaluate_policy_actor_identity,
)
from sena.api.runtime import EngineState, evaluate_abac_policy, is_role_allowed
from sena.services.audit_service import AuditService

logger = get_logger(__name__)


class FixedWindowRateLimiter:
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


def register_request_middleware(
    app: FastAPI,
    *,
    state: EngineState,
    auth_manager: AuthManager,
    rate_limiter: FixedWindowRateLimiter,
) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        def _extract_trace_context() -> tuple[str, str]:
            traceparent = request.headers.get("traceparent", "")
            parts = traceparent.split("-")
            if len(parts) == 4 and len(parts[1]) == 32 and len(parts[2]) == 16:
                return parts[1], parts[2]
            return uuid.uuid4().hex, uuid.uuid4().hex[:16]

        request_id = (
            request.headers.get("x-request-id") or f"req_{uuid.uuid4().hex[:12]}"
        )
        trace_id, span_id = _extract_trace_context()
        request.state.request_id = request_id
        request.state.trace_id = trace_id
        request.state.span_id = span_id
        bind_request_context(request_id=request_id, trace_id=trace_id, span_id=span_id)

        started = time.perf_counter()
        client_key = request.headers.get("x-api-key", "")
        if not client_key:
            client_host = request.client.host if request.client else "unknown"
            client_key = f"anonymous:{client_host}"

        def _json_error(
            status_code: int,
            code: str,
            message: str,
            *,
            details: dict[str, Any] | None = None,
        ) -> JSONResponse:
            error_response = JSONResponse(
                status_code=status_code,
                content=error_payload(code, message, request_id, details=details),
            )
            error_response.headers["x-request-id"] = request_id
            error_response.headers["x-trace-id"] = trace_id
            error_response.headers["traceparent"] = f"00-{trace_id}-{span_id}-01"
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            state.metrics.observe_request(
                method=request.method,
                path=request.url.path,
                status_code=status_code,
            )
            state.metrics.observe_request_latency(
                method=request.method,
                path=request.url.path,
                duration_seconds=duration_ms / 1000,
            )
            state.metrics.observe_api_error(
                path=request.url.path,
                error_code=code,
                status_code=status_code,
            )
            if state.recovery_service is not None:
                state.recovery_service.record(
                    path=request.url.path, status_code=status_code
                )
            logger.info(
                "request_processed",
                method=request.method,
                path=request.url.path,
                status_code=status_code,
                duration_ms=duration_ms,
                error_code=code,
            )
            clear_request_context()
            return error_response

        content_length = request.headers.get("content-length")
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError:
                return _json_error(
                    400, "invalid_content_length", "Invalid Content-Length header"
                )
            if declared_size > state.settings.request_max_bytes:
                return _json_error(
                    413, "payload_too_large", "Request payload exceeds maximum size"
                )

        body = await request.body()
        if len(body) > state.settings.request_max_bytes:
            return _json_error(
                413, "payload_too_large", "Request payload exceeds maximum size"
            )

        async def _receive() -> dict[str, Any]:
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = _receive  # type: ignore[attr-defined]

        try:
            principal = auth_manager.authenticate_request(request)
        except AuthError as exc:
            return _json_error(exc.status_code, exc.code, exc.message)
        request.state.auth_principal = principal
        request.state.api_role = principal.role if principal else ""
        if principal is not None:
            client_key = principal.subject
            role = principal.role
            if not is_role_allowed(role, request.method, request.url.path):
                return _json_error(
                    403,
                    "forbidden",
                    "Authenticated role is not authorized for this endpoint",
                    details={
                        "reason": "route_not_allowed",
                        "role": role,
                        "method": request.method,
                        "path": request.url.path,
                    },
                )
            body_payload: dict[str, Any] = {}
            if body:
                try:
                    import json

                    decoded = json.loads(body.decode("utf-8"))
                    if isinstance(decoded, dict):
                        body_payload = decoded
                except Exception:
                    body_payload = {}
            environment = request.headers.get("x-sena-environment") or state.settings.runtime_mode
            bundle_name = (
                request.headers.get("x-sena-bundle-name")
                or request.query_params.get("bundle_name")
                or body_payload.get("bundle_name")
            )
            action_type = body_payload.get("action_type")
            actor_identity_decision = evaluate_policy_actor_identity(
                principal=principal,
                request_path=request.url.path,
                body_payload=body_payload,
                enforce=state.settings.enforce_policy_actor_identity,
            )
            if not actor_identity_decision.allowed:
                return _json_error(
                    403,
                    "forbidden",
                    actor_identity_decision.reason or "Policy actor identity denied request",
                    details=actor_identity_decision.details() or None,
                )
            abac_allowed, abac_reason = evaluate_abac_policy(
                role=role,
                environment=environment,
                bundle_name=bundle_name,
                action_type=action_type,
                expected_bundle_name=state.settings.bundle_name,
            )
            if not abac_allowed:
                return _json_error(
                    403,
                    "forbidden",
                    abac_reason or "ABAC policy denied request",
                    details={
                        "reason": "abac_policy_denied",
                        "environment": environment,
                        "bundle_name": bundle_name or state.settings.bundle_name,
                        "action_type": action_type,
                    },
                )

        if not rate_limiter.allow(client_key, time.monotonic()):
            return _json_error(429, "rate_limited", "Rate limit exceeded")

        try:
            response = await asyncio.wait_for(
                call_next(request), timeout=state.settings.request_timeout_seconds
            )
        except asyncio.TimeoutError:
            return _json_error(504, "timeout", "Request processing timed out")
        except Exception:
            clear_request_context()
            raise

        response.headers["x-request-id"] = request_id
        response.headers["x-trace-id"] = trace_id
        response.headers["traceparent"] = f"00-{trace_id}-{span_id}-01"
        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        state.metrics.observe_request(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
        )
        state.metrics.observe_request_latency(
            method=request.method,
            path=request.url.path,
            duration_seconds=duration_ms / 1000,
        )
        if state.recovery_service is not None:
            state.recovery_service.record(
                path=request.url.path, status_code=response.status_code
            )
        logger.info(
            "request_processed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        is_admin_action = request.url.path.startswith(("/v1/bundle", "/v1/admin")) and request.method in {"POST", "PUT", "PATCH", "DELETE"}
        if is_admin_action and state.settings.audit_sink_jsonl:
            try:
                AuditService(state.settings.audit_sink_jsonl).append_record(
                    {
                        "event_type": "api.admin_action",
                        "path": request.url.path,
                        "method": request.method,
                        "status_code": response.status_code,
                        "request_id": request_id,
                        "role": getattr(request.state, "api_role", "anonymous"),
                        "environment": request.headers.get("x-sena-environment")
                        or state.settings.runtime_mode,
                        "bundle_name": request.headers.get("x-sena-bundle-name")
                        or request.query_params.get("bundle_name")
                        or state.settings.bundle_name,
                    }
                )
            except Exception:
                logger.exception("failed_to_write_admin_audit_record")
        clear_request_context()
        return response
