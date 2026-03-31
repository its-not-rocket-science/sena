import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from sena.api.app import create_app
from sena.api.config import ApiSettings



def _settings(**kwargs):
    defaults = {
        "policy_dir": "src/sena/examples/policies",
        "bundle_name": "enterprise-demo",
        "bundle_version": "2026.03",
        "enable_api_key_auth": False,
        "api_key": None,
        "audit_sink_jsonl": None,
    }
    defaults.update(kwargs)
    return ApiSettings(**defaults)



def test_health_endpoint() -> None:
    app = create_app(_settings())
    client = TestClient(app)

    response = client.get("/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "sena-api"
    assert "integrity_sha256" in body["bundle"]



def test_readiness_endpoint() -> None:
    app = create_app(_settings())
    client = TestClient(app)

    response = client.get("/v1/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"



def test_evaluate_endpoint_returns_decision_and_bundle() -> None:
    app = create_app(_settings())
    client = TestClient(app)

    response = client.post(
        "/v1/evaluate",
        json={
            "action_type": "approve_vendor_payment",
            "attributes": {
                "amount": 15000,
                "vendor_verified": False,
                "requester_role": "finance_analyst",
            },
            "facts": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "BLOCKED"
    assert body["decision"] == "BLOCKED"
    assert body["decision_id"].startswith("dec_")
    assert body["policy_bundle"]["version"] == "2026.03"
    assert "decision_hash" in body



def test_api_key_auth_blocks_unauthorized_request() -> None:
    app = create_app(_settings(enable_api_key_auth=True, api_key="secret"))
    client = TestClient(app)

    response = client.post("/v1/evaluate", json={"action_type": "approve_vendor_payment"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"



def test_api_key_auth_allows_authorized_request() -> None:
    app = create_app(_settings(enable_api_key_auth=True, api_key="secret"))
    client = TestClient(app)

    response = client.post(
        "/v1/evaluate",
        headers={"x-api-key": "secret"},
        json={"action_type": "approve_vendor_payment", "attributes": {"vendor_verified": False}},
    )
    assert response.status_code == 200



def test_validation_error_shape() -> None:
    app = create_app(_settings())
    client = TestClient(app)

    response = client.post("/v1/evaluate", json={"action_type": ""})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
