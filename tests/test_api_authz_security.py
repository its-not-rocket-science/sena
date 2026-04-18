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
        "enable_api_key_auth": True,
        "api_keys": (("audit-key", "auditor"), ("deploy-key", "deployer")),
        "audit_sink_jsonl": None,
        "rate_limit_requests": 120,
        "rate_limit_window_seconds": 60,
        "request_max_bytes": 1_048_576,
        "request_timeout_seconds": 15.0,
    }
    defaults.update(kwargs)
    return ApiSettings(**defaults)


def _signed_step_up_assertion(
    *,
    secret: str,
    subject: str,
    operation: str,
    secondary_approver: str | None = None,
    iat: int | None = None,
) -> str:
    payload = {
        "subject": subject,
        "operation": operation,
        "iat": iat or int(time.time()),
    }
    if secondary_approver:
        payload["secondary_approver"] = secondary_approver
    payload_segment = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).rstrip(b"=").decode("utf-8")
    signing_input = f"v1.{payload_segment}".encode("utf-8")
    signature_segment = base64.urlsafe_b64encode(
        hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    ).rstrip(b"=").decode("utf-8")
    return f"v1.{payload_segment}.{signature_segment}"


def test_payload_legal_hold_requires_step_up_for_auditor() -> None:
    client = TestClient(create_app(_settings()))

    response = client.post(
        "/v1/admin/data/payloads/1/hold",
        headers={"x-api-key": "audit-key"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["details"]["reason"] == "step_up_auth_required"


def test_audit_hold_requires_step_up_for_auditor() -> None:
    client = TestClient(create_app(_settings()))

    response = client.post(
        "/v1/audit/hold/dec_123",
        headers={"x-api-key": "audit-key"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["details"]["reason"] == "step_up_auth_required"


def test_dead_letter_replay_enforcement_is_route_consistent() -> None:
    client = TestClient(create_app(_settings()))

    denied = client.post(
        "/v1/integrations/jira/admin/outbound/dead-letter/replay",
        headers={"x-api-key": "audit-key"},
        json=[1],
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["details"]["reason"] == "step_up_auth_required"

    allowed_to_proceed = client.post(
        "/v1/integrations/jira/admin/outbound/dead-letter/replay",
        headers={"x-api-key": "audit-key", "x-step-up-auth": "mfa-ok"},
        json=[1],
    )
    assert allowed_to_proceed.status_code == 400
    assert allowed_to_proceed.json()["error"]["code"] == "jira_mapping_not_configured"


def test_signed_step_up_rejects_forged_header_for_bundle_promotion() -> None:
    client = TestClient(
        create_app(
            _settings(
                require_signed_step_up=True,
                step_up_hs256_secret="step-up-secret",
            )
        )
    )

    response = client.post(
        "/v1/bundle/promote",
        headers={
            "x-api-key": "deploy-key",
            "x-step-up-auth": "mfa-ok",
            "x-approver-id": "deployer-1",
            "x-secondary-approver-id": "auditor-2",
        },
        json={
            "bundle_id": 1,
            "target_lifecycle": "active",
            "promoted_by": "u",
            "promotion_reason": "r",
            "validation_artifact": "a",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["details"]["reason"] == "step_up_assertion_invalid"


def test_signed_step_up_rejects_subject_mismatch() -> None:
    assertion = _signed_step_up_assertion(
        secret="step-up-secret",
        subject="different-subject",
        operation="integration_dead_letter_manual_redrive",
        secondary_approver="auditor-2",
    )
    client = TestClient(
        create_app(
            _settings(
                require_signed_step_up=True,
                step_up_hs256_secret="step-up-secret",
            )
        )
    )

    response = client.post(
        "/v1/integrations/jira/admin/outbound/dead-letter/manual-redrive",
        headers={
            "x-api-key": "audit-key",
            "x-step-up-auth": assertion,
        },
        json=[1],
    )

    assert response.status_code == 403
    assert response.json()["error"]["details"]["reason"] == "step_up_subject_mismatch"
