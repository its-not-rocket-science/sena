from __future__ import annotations

import threading
import time

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


def test_evaluate_idempotency_concurrent_same_key_same_payload_replays(tmp_path) -> None:
    app = create_app(_settings(tmp_path))
    client = TestClient(app)
    original = app.state.engine_state.processing_service.enqueue_and_process

    def delayed_enqueue(event):
        if event.get("event_type") == "evaluate":
            time.sleep(0.15)
        return original(event)

    app.state.engine_state.processing_service.enqueue_and_process = delayed_enqueue
    payload = {
        "action_type": "approve_vendor_payment",
        "attributes": {"vendor_verified": False},
    }
    responses: list = []

    def send() -> None:
        responses.append(
            client.post(
                "/v1/evaluate",
                headers={"Idempotency-Key": "idem-concurrent"},
                json=payload,
            )
        )

    first = threading.Thread(target=send)
    second = threading.Thread(target=send)
    first.start()
    second.start()
    first.join()
    second.join()

    assert len(responses) == 2
    assert responses[0].status_code == 200
    assert responses[1].status_code == 200
    assert responses[0].json()["decision_id"] == responses[1].json()["decision_id"]


def test_evaluate_idempotency_survives_restart(tmp_path) -> None:
    settings = _settings(tmp_path)
    first_app = create_app(settings)
    first_client = TestClient(first_app)
    payload = {
        "action_type": "approve_vendor_payment",
        "attributes": {"vendor_verified": False},
    }
    first = first_client.post(
        "/v1/evaluate",
        headers={"Idempotency-Key": "idem-restart"},
        json=payload,
    )

    second_app = create_app(settings)
    second_client = TestClient(second_app)
    second = second_client.post(
        "/v1/evaluate",
        headers={"Idempotency-Key": "idem-restart"},
        json=payload,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["decision_id"] == second.json()["decision_id"]
