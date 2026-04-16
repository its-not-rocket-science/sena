from __future__ import annotations

import json
import os

from fastapi import Depends, Header, HTTPException, Request, Security
from fastapi.responses import Response
from fastapi.security import APIKeyHeader

from sena.api.runtime import EngineState

api_key_header = APIKeyHeader(name="X-API-Key")


def get_engine_state(request: Request) -> EngineState:
    return request.app.state.engine_state


def _load_valid_api_keys() -> tuple[str, ...]:
    raw_keys = os.getenv("SENA_API_KEYS", "")
    keys: list[str] = []
    for item in raw_keys.split(","):
        entry = item.strip()
        if not entry:
            continue
        key, sep, _ = entry.partition(":")
        keys.append(key.strip() if sep else entry)
    return tuple(key for key in keys if key)


async def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    valid_keys = _load_valid_api_keys()
    if api_key not in valid_keys:
        raise HTTPException(status_code=403)
    return api_key


async def check_idempotency_key(
    request: Request, key: str | None = Header(None, alias="Idempotency-Key")
) -> Response | None:
    if not key:
        return None
    existing = request.app.state.engine_state.processing_store.get_idempotency_response(key)
    if existing is None:
        return None
    return Response(content=existing, media_type="application/json", status_code=200)


def persist_idempotency_response(request: Request, response_payload: dict) -> None:
    key = request.headers.get("Idempotency-Key")
    if not key:
        return
    request.app.state.engine_state.processing_store.store_idempotency_response(
        key,
        json.dumps(response_payload, sort_keys=True),
        ttl_hours=request.app.state.engine_state.settings.idempotency_ttl_hours,
    )


ApiKeyDependency = Depends(verify_api_key)
