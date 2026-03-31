import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from sena.api.app import create_app


def test_health_endpoint() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "bundle" in body


def test_evaluate_endpoint_returns_decision_and_bundle() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/evaluate",
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
    assert body["policy_bundle"]["version"] == "0.1.0-alpha"
