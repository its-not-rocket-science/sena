from __future__ import annotations

import json
import os
from hashlib import sha256

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
    existing = request.app.state.engine_state.processing_store.get_idempotency_entry(key)
    if existing is None:
        return None
    existing_response, existing_fingerprint = existing
    incoming_payload: dict | None = None
    if request.method in {"POST", "PUT", "PATCH"}:
        raw_body = await request.body()
        if raw_body:
            try:
                parsed = json.loads(raw_body)
                if isinstance(parsed, dict):
                    incoming_payload = parsed
            except json.JSONDecodeError:
                incoming_payload = None
    incoming_fingerprint = idempotency_request_fingerprint(request, incoming_payload)
    if (
        existing_fingerprint is not None
        and incoming_fingerprint is not None
        and existing_fingerprint != incoming_fingerprint
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "idempotency_key_conflict",
                "message": "Idempotency-Key has already been used with a different payload.",
            },
        )
    return Response(content=existing_response, media_type="application/json", status_code=200)


def idempotency_request_fingerprint(request: Request, payload: dict | None) -> str | None:
    key = request.headers.get("Idempotency-Key")
    if not key:
        return None
    canonical_payload = json.dumps(payload if payload is not None else {}, sort_keys=True)
    fingerprint_material = f"{request.url.path}|{canonical_payload}"
    return sha256(fingerprint_material.encode("utf-8")).hexdigest()


def claim_or_replay_idempotency(
    request: Request,
    *,
    request_payload: dict | None = None,
    wait_timeout_seconds: float = 5.0,
) -> Response | None:
    key = request.headers.get("Idempotency-Key")
    if not key:
        return None
    fingerprint = idempotency_request_fingerprint(request, request_payload)
    if fingerprint is None:
        return None
    result, cached_response, claim_token = (
        request.app.state.engine_state.processing_store.claim_idempotency_key(
            key,
            request_fingerprint=fingerprint,
            ttl_hours=request.app.state.engine_state.settings.idempotency_ttl_hours,
        )
    )
    if result == "claimed":
        request.state.idempotency_claim_token = claim_token
        return None
    if result == "replay" and cached_response is not None:
        return Response(content=cached_response, media_type="application/json", status_code=200)
    if result == "conflict":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "idempotency_key_conflict",
                "message": "Idempotency-Key has already been used with a different payload.",
            },
        )
    cached_after_wait = request.app.state.engine_state.processing_store.wait_for_idempotency_completion(
        key,
        request_fingerprint=fingerprint,
        timeout_seconds=wait_timeout_seconds,
    )
    if cached_after_wait is not None:
        return Response(content=cached_after_wait, media_type="application/json", status_code=200)
    raise HTTPException(
        status_code=409,
        detail={
            "code": "idempotency_key_in_progress",
            "message": "Idempotency-Key is already in progress for this payload.",
        },
    )


def persist_idempotency_response(
    request: Request,
    response_payload: dict,
    *,
    request_payload: dict | None = None,
) -> None:
    key = request.headers.get("Idempotency-Key")
    if not key:
        return
    claim_token = getattr(request.state, "idempotency_claim_token", None)
    response_json = json.dumps(response_payload, sort_keys=True)
    ttl_hours = request.app.state.engine_state.settings.idempotency_ttl_hours
    if claim_token:
        request.app.state.engine_state.processing_store.finalize_idempotency_key(
            key,
            claim_token=claim_token,
            response_json=response_json,
            ttl_hours=ttl_hours,
        )
        return
    request.app.state.engine_state.processing_store.store_idempotency_response(
        key,
        response_json,
        ttl_hours=ttl_hours,
        request_fingerprint=idempotency_request_fingerprint(request, request_payload),
    )


ApiKeyDependency = Depends(verify_api_key)
