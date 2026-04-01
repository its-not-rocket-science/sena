from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict, deque
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from sena.api.error_handlers import error_payload
from sena.api.runtime import EngineState, is_role_allowed

logger = logging.getLogger(__name__)


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
    api_key_roles: dict[str, str],
    rate_limiter: FixedWindowRateLimiter,
) -> None:
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
                content=error_payload(code, message, request_id),
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
            if not is_role_allowed(role, request.method, request.url.path):
                return _json_error(403, "forbidden", "API key role is not authorized for this endpoint")

        if not rate_limiter.allow(client_key, time.monotonic()):
            return _json_error(429, "rate_limited", "Rate limit exceeded")

        try:
            response = await asyncio.wait_for(call_next(request), timeout=state.settings.request_timeout_seconds)
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
