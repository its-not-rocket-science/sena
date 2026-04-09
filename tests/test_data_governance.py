from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from sena.api.app import create_app
from sena.api.config import ApiSettings
from sena.api.processing_store import ProcessingStore


def _settings(tmp_path):
    return ApiSettings(
        policy_dir="src/sena/examples/policies",
        bundle_name="enterprise-demo",
        bundle_version="2026.03",
        processing_sqlite_path=str(tmp_path / "runtime.db"),
        webhook_mapping_config_path="src/sena/examples/integrations/webhook_mappings.yaml",
        data_default_region="us-east-1",
        data_allowed_regions=("us-east-1", "eu-west-1"),
        payload_retention_ttl_hours=1,
    )


def test_evaluate_pii_payload_is_redacted_and_region_scoped(tmp_path) -> None:
    app = create_app(_settings(tmp_path))
    client = TestClient(app)

    response = client.post(
        "/v1/evaluate",
        json={
            "action_type": "approve_vendor_payment",
            "tenant_id": "tenant-finance",
            "region": "eu-west-1",
            "attributes": {
                "requester_email": "analyst@example.com",
                "card_number": "4111 1111 1111 1111",
                "vendor_verified": False,
            },
        },
    )

    assert response.status_code == 200

    stored = app.state.engine_state.processing_store.list_governed_payloads(
        tenant_id="tenant-finance",
        region="eu-west-1",
    )
    assert len(stored) == 1
    pii_flags = json.loads(stored[0]["pii_flags_json"])
    assert "attributes.requester_email" in pii_flags
    assert "attributes.card_number" in pii_flags
    redacted = json.loads(stored[0]["redacted_payload_json"])
    assert redacted["attributes"]["requester_email"] == "[REDACTED]"
    assert redacted["attributes"]["card_number"] == "[REDACTED]"


def test_region_pinning_rejects_non_allowed_region(tmp_path) -> None:
    app = create_app(_settings(tmp_path))
    client = TestClient(app)

    response = client.post(
        "/v1/evaluate",
        json={
            "action_type": "approve_vendor_payment",
            "tenant_id": "tenant-finance",
            "region": "ap-southeast-2",
            "attributes": {"vendor_verified": True},
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "evaluation_error"


def test_governed_payload_legal_hold_blocks_retention_purge(tmp_path) -> None:
    store = ProcessingStore(str(tmp_path / "runtime.db"))
    payload_id = store.store_governed_payload(
        tenant_id="tenant-finance",
        region="us-east-1",
        payload_type="evaluate_request",
        payload={"card_number": "4111111111111111"},
        redacted_payload={"card_number": "[REDACTED]"},
        pii_flags=["card_number"],
        ttl_hours=0,
    )
    held = store.apply_governed_payload_legal_hold(payload_id, reason="investigation")

    deleted = store.purge_expired_governed_payloads()
    all_rows = store.list_governed_payloads(
        tenant_id="tenant-finance", region="us-east-1", include_expired=True
    )

    assert held is True
    assert deleted == 0
    assert any(int(row["id"]) == payload_id for row in all_rows)


def test_admin_data_access_events_endpoint(tmp_path) -> None:
    app = create_app(_settings(tmp_path))
    client = TestClient(app)

    evaluate = client.post(
        "/v1/evaluate",
        json={
            "action_type": "approve_vendor_payment",
            "tenant_id": "tenant-finance",
            "region": "us-east-1",
            "attributes": {"vendor_verified": True},
        },
    )
    assert evaluate.status_code == 200

    events = client.get("/v1/admin/data-access")
    assert events.status_code == 200
    items = events.json()["items"]
    assert any(item["entity_type"] == "governed_payload" for item in items)
