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


def test_batch_and_bundle_inspect_endpoints() -> None:
    app = create_app(_settings())
    client = TestClient(app)

    inspect_response = client.get("/v1/bundle/inspect")
    assert inspect_response.status_code == 200
    assert inspect_response.json()["rules_total"] > 0

    batch_response = client.post(
        "/v1/evaluate/batch",
        json={"items": [{"action_type": "approve_vendor_payment", "attributes": {"vendor_verified": False}}]},
    )
    assert batch_response.status_code == 200
    assert batch_response.json()["count"] == 1


def test_simulation_endpoint() -> None:
    app = create_app(_settings())
    client = TestClient(app)
    response = client.post(
        "/v1/simulation",
        json={
            "baseline_policy_dir": "src/sena/examples/policies",
            "candidate_policy_dir": "src/sena/examples/policies",
            "scenarios": [
                {
                    "scenario_id": "s1",
                    "action_type": "approve_vendor_payment",
                    "attributes": {"vendor_verified": False},
                    "facts": {},
                }
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["total_scenarios"] == 1


def test_sqlite_policy_store_mode(tmp_path) -> None:
    db_path = tmp_path / "policy_registry.db"

    seed_app = create_app(
        _settings(
            policy_store_backend="filesystem",
            policy_store_sqlite_path=str(db_path),
        )
    )
    seed_client = TestClient(seed_app)

    response = seed_client.post(
        "/v1/bundle/register",
        json={
            "policy_dir": "src/sena/examples/policies",
            "bundle_name": "enterprise-compliance-controls",
            "bundle_version": "2026.03",
            "lifecycle": "candidate",
        },
    )
    assert response.status_code == 400

    from sena.policy.parser import load_policy_bundle
    from sena.policy.store import SQLitePolicyBundleRepository

    repo = SQLitePolicyBundleRepository(str(db_path))
    repo.initialize()
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    metadata.lifecycle = "draft"
    bundle_id = repo.register_bundle(metadata, rules)
    repo.set_bundle_lifecycle(bundle_id, "candidate")
    repo.set_bundle_lifecycle(bundle_id, "active")

    app = create_app(
        _settings(
            policy_store_backend="sqlite",
            policy_store_sqlite_path=str(db_path),
            bundle_name="enterprise-compliance-controls",
        )
    )
    client = TestClient(app)

    active = client.get("/v1/bundles/active")
    assert active.status_code == 200
    assert active.json()["bundle"]["lifecycle"] == "active"

    eval_response = client.post(
        "/v1/evaluate",
        json={"action_type": "approve_vendor_payment", "attributes": {"vendor_verified": False}},
    )
    assert eval_response.status_code == 200


def test_bundle_promote_endpoint_enforces_transition_order(tmp_path) -> None:
    db_path = tmp_path / "policy_registry.db"
    from sena.policy.parser import load_policy_bundle
    from sena.policy.store import SQLitePolicyBundleRepository

    repo = SQLitePolicyBundleRepository(str(db_path))
    repo.initialize()
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    metadata.lifecycle = "draft"
    bundle_id = repo.register_bundle(metadata, rules)

    app = create_app(
        _settings(
            policy_store_backend="sqlite",
            policy_store_sqlite_path=str(db_path),
            bundle_name=metadata.bundle_name,
        )
    )
    client = TestClient(app)

    skipped = client.post(
        "/v1/bundle/promote",
        json={"bundle_id": bundle_id, "target_lifecycle": "active"},
    )
    assert skipped.status_code == 400

    to_candidate = client.post(
        "/v1/bundle/promote",
        json={"bundle_id": bundle_id, "target_lifecycle": "candidate"},
    )
    assert to_candidate.status_code == 200


def test_webhook_endpoint_maps_payload_and_returns_reasoning() -> None:
    app = create_app(
        _settings(
            webhook_mapping_config_path="src/sena/examples/integrations/webhook_mappings.yaml"
        )
    )
    client = TestClient(app)

    response = client.post(
        "/v1/integrations/webhook",
        json={
            "provider": "stripe",
            "event_type": "payment_intent.created",
            "payload": {
                "id": "evt_123",
                "data": {
                    "object": {
                        "amount": 25000,
                        "currency": "usd",
                        "metadata": {
                            "vendor_verified": False,
                            "requester_role": "finance_analyst",
                            "requested_by": "user_9"
                        }
                    }
                }
            },
            "facts": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "stripe"
    assert body["mapped_action_proposal"]["action_type"] == "approve_vendor_payment"
    assert body["mapped_action_proposal"]["attributes"]["source_system"] == "stripe"
    assert body["decision"]["outcome"] == "BLOCKED"
    assert body["reasoning"]["summary"]


def test_webhook_endpoint_requires_mapping_config() -> None:
    app = create_app(_settings())
    client = TestClient(app)

    response = client.post(
        "/v1/integrations/webhook",
        json={"provider": "stripe", "event_type": "payment_intent.created", "payload": {}},
    )

    assert response.status_code == 400
