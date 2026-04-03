from __future__ import annotations

import os

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from sena.api.runtime import EngineState

api_key_header = APIKeyHeader(name="X-API-Key")


def get_engine_state(request: Request) -> EngineState:
    return request.app.state.engine_state


def _load_valid_api_keys() -> tuple[str, ...]:
    raw_keys = os.getenv("SENA_API_KEYS", "")
    return tuple(item.strip() for item in raw_keys.split(",") if item.strip())


async def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    valid_keys = _load_valid_api_keys()
    if api_key not in valid_keys:
        raise HTTPException(status_code=403)
    return api_key


ApiKeyDependency = Depends(verify_api_key)
