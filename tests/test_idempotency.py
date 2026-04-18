from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from sena.api.app import create_app
from sena.api.config import ApiSettings


def _settings(tmp_path):
    return ApiSettings(
        policy_dir="src/sena/examples/policies",
        bundle_name="enterprise-demo",
        bundle_version="2026.03",
        processing_sqlite_path=str(tmp_path / "runtime.db"),
        webhook_mapping_config_path="src/sena/examples/integrations/webhook_mappings.yaml",
    )


def test_evaluate_idempotency_key_returns_cached_response(tmp_path) -> None:
    app = create_app(_settings(tmp_path))
    client = TestClient(app)

    payload = {
        "action_type": "approve_vendor_payment",
        "attributes": {"vendor_verified": False},
    }
    first = client.post(
        "/v1/evaluate",
        headers={"Idempotency-Key": "idem-1"},
        json=payload,
    )
    second = client.post(
        "/v1/evaluate",
        headers={"Idempotency-Key": "idem-1"},
        json=payload,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["decision_id"] == second.json()["decision_id"]


def test_evaluate_idempotency_key_conflicts_on_semantic_payload_change(tmp_path) -> None:
    app = create_app(_settings(tmp_path))
    client = TestClient(app)

    first = client.post(
        "/v1/evaluate",
        headers={"Idempotency-Key": "idem-1-conflict"},
        json={
            "action_type": "approve_vendor_payment",
            "attributes": {"vendor_verified": False},
        },
    )
    second = client.post(
        "/v1/evaluate",
        headers={"Idempotency-Key": "idem-1-conflict"},
        json={
            "action_type": "approve_vendor_payment",
            "attributes": {"vendor_verified": True},
        },
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["details"]["reason"] == "idempotency_key_conflict"


def test_webhook_idempotency_key_returns_cached_response(tmp_path) -> None:
    app = create_app(_settings(tmp_path))
    client = TestClient(app)

    body = {
        "provider": "stripe",
        "event_type": "payment_intent.created",
        "payload": {
            "data": {
                "object": {
                    "id": "pi_123",
                    "amount": 1000,
                    "currency": "usd",
                    "metadata": {
                        "requested_by": "alice",
                        "vendor_verified": False,
                        "requester_role": "finance_analyst",
                    },
                }
            }
        },
        "facts": {},
    }

    first = client.post(
        "/v1/integrations/webhook",
        headers={"Idempotency-Key": "idem-2"},
        json=body,
    )
    second = client.post(
        "/v1/integrations/webhook",
        headers={"Idempotency-Key": "idem-2"},
        json=body,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["decision"]["decision_id"] == second.json()["decision"]["decision_id"]


def test_webhook_idempotency_key_conflicts_on_semantic_payload_change(tmp_path) -> None:
    app = create_app(_settings(tmp_path))
    client = TestClient(app)

    first = client.post(
        "/v1/integrations/webhook",
        headers={"Idempotency-Key": "idem-2-conflict"},
        json={
            "provider": "stripe",
            "event_type": "payment_intent.created",
            "payload": {
                "data": {
                    "object": {
                        "id": "pi_123",
                        "amount": 1000,
                        "currency": "usd",
                        "metadata": {
                            "requested_by": "alice",
                            "vendor_verified": False,
                            "requester_role": "finance_analyst",
                        },
                    }
                }
            },
            "facts": {},
        },
    )
    second = client.post(
        "/v1/integrations/webhook",
        headers={"Idempotency-Key": "idem-2-conflict"},
        json={
            "provider": "stripe",
            "event_type": "payment_intent.created",
            "payload": {
                "data": {
                    "object": {
                        "id": "pi_123",
                        "amount": 1000,
                        "currency": "usd",
                        "metadata": {
                            "requested_by": "alice",
                            "vendor_verified": True,
                            "requester_role": "finance_analyst",
                        },
                    }
                }
            },
            "facts": {},
        },
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["details"]["reason"] == "idempotency_key_conflict"
