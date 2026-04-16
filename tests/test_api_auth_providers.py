from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from sena.api.app import create_app
from sena.api.config import ApiSettings


def _settings(**kwargs) -> ApiSettings:
    defaults = {
        "policy_dir": "src/sena/examples/policies",
        "bundle_name": "enterprise-demo",
        "bundle_version": "2026.03",
        "enable_api_key_auth": False,
        "api_key": None,
        "api_keys": (),
        "enable_jwt_auth": True,
        "jwt_hs256_secret": "local-dev-secret",
        "jwt_role_claim": "roles",
        "jwt_role_mapping": (("idp-reviewer", "reviewer"),),
        "audit_sink_jsonl": None,
        "rate_limit_requests": 120,
        "rate_limit_window_seconds": 60,
        "request_max_bytes": 1_048_576,
        "request_timeout_seconds": 15.0,
    }
    defaults.update(kwargs)
    return ApiSettings(**defaults)


def _hs256_token(payload: dict, *, secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}

    def _b64(data: dict) -> str:
        encoded = json.dumps(data, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode("utf-8")

    header_part = _b64(header)
    payload_part = _b64(payload)
    signing_input = f"{header_part}.{payload_part}".encode("utf-8")
    signature = base64.urlsafe_b64encode(
        hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    ).rstrip(b"=")
    return f"{header_part}.{payload_part}.{signature.decode('utf-8')}"


def test_jwt_auth_rejects_malformed_token() -> None:
    client = TestClient(create_app(_settings()))

    response = client.get(
        "/v1/exceptions/active",
        headers={"authorization": "Bearer malformed"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_authentication"


def test_jwt_auth_rejects_missing_role_claim() -> None:
    client = TestClient(create_app(_settings()))
    token = _hs256_token(
        {
            "sub": "user-1",
            "exp": int(time.time()) + 3600,
        },
        secret="local-dev-secret",
    )

    response = client.get(
        "/v1/exceptions/active",
        headers={"authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["details"]["reason"] == "role_mapping_failed"


def test_jwt_auth_rejects_unmapped_role() -> None:
    client = TestClient(create_app(_settings()))
    token = _hs256_token(
        {
            "sub": "user-1",
            "roles": ["idp-unknown"],
            "exp": int(time.time()) + 3600,
        },
        secret="local-dev-secret",
    )

    response = client.get(
        "/v1/exceptions/active",
        headers={"authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["details"]["reason"] == "role_mapping_failed"


def test_jwt_auth_accepts_mapped_role() -> None:
    client = TestClient(create_app(_settings()))
    token = _hs256_token(
        {
            "sub": "user-1",
            "roles": ["idp-reviewer"],
            "exp": int(time.time()) + 3600,
        },
        secret="local-dev-secret",
    )

    response = client.get(
        "/v1/exceptions/active",
        headers={"authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200


def test_policy_actor_identity_mismatch_rejected_when_enabled() -> None:
    client = TestClient(
        create_app(
            _settings(
                enforce_policy_actor_identity=True,
                jwt_role_mapping=(("idp-reviewer", "reviewer"), ("idp-admin", "admin")),
            )
        )
    )
    token = _hs256_token(
        {
            "sub": "identity-123",
            "roles": ["idp-reviewer"],
            "exp": int(time.time()) + 3600,
        },
        secret="local-dev-secret",
    )

    response = client.post(
        "/v1/evaluate",
        headers={"authorization": f"Bearer {token}"},
        json={"action_type": "approve_payment", "actor_id": "other-user"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["details"]["reason"] == "actor_identity_mismatch"
