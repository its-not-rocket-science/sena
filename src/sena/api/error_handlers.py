from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from sena.api.errors import ERROR_CODE_CATALOG


def error_payload(code: str, message: str, request_id: str | None = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    }


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        payload = error_payload(
            "validation_error",
            ERROR_CODE_CATALOG["validation_error"].message,
            request.state.request_id,
        )
        payload["error"]["details"] = exc.errors()
        return JSONResponse(status_code=422, content=payload)

    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        code = detail.get("code", "http_internal_error")
        default_message = ERROR_CODE_CATALOG.get(
            code, ERROR_CODE_CATALOG["http_internal_error"]
        ).message
        message = detail.get("message", default_message)
        payload = error_payload(code, message, request.state.request_id)
        if "details" in detail:
            payload["error"]["details"] = detail["details"]
        return JSONResponse(status_code=exc.status_code, content=payload)
