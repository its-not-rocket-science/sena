import pytest
import time

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
        "api_keys": (),
        "audit_sink_jsonl": None,
        "rate_limit_requests": 120,
        "rate_limit_window_seconds": 60,
        "request_max_bytes": 1_048_576,
        "request_timeout_seconds": 15.0,
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


def test_unversioned_routes_are_deprecated_and_removed() -> None:
    app = create_app(_settings())
    client = TestClient(app)

    health_response = client.get("/health")
    assert health_response.status_code == 410
    assert health_response.json()["error"]["code"] == "route_deprecated"
    assert health_response.headers["Deprecation"] == "true"
    assert health_response.headers["Sunset"] == "2026-04-01"
    assert "/v1/health" in health_response.json()["error"]["message"]

    bundle_response = client.get("/bundle")
    assert bundle_response.status_code == 410
    assert bundle_response.json()["error"]["code"] == "route_deprecated"
    assert "/v1/bundle" in bundle_response.json()["error"]["message"]

    evaluate_response = client.post("/evaluate", json={"action_type": "approve_vendor_payment"})
    assert evaluate_response.status_code == 410
    assert evaluate_response.json()["error"]["code"] == "route_deprecated"
    assert "/v1/evaluate" in evaluate_response.json()["error"]["message"]



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


def test_api_key_role_evaluator_cannot_promote_bundle() -> None:
    app = create_app(_settings(enable_api_key_auth=True, api_keys=(("eval-key", "evaluator"),)))
    client = TestClient(app)

    response = client.post(
        "/v1/bundle/promote",
        headers={"x-api-key": "eval-key"},
        json={"bundle_id": 1, "target_lifecycle": "active"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_api_key_role_policy_author_cannot_evaluate() -> None:
    app = create_app(
        _settings(enable_api_key_auth=True, api_keys=(("author-key", "policy_author"),))
    )
    client = TestClient(app)

    response = client.post(
        "/v1/evaluate",
        headers={"x-api-key": "author-key"},
        json={"action_type": "approve_vendor_payment"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"



def test_validation_error_shape() -> None:
    app = create_app(_settings())
    client = TestClient(app)

    response = client.post("/v1/evaluate", json={"action_type": ""})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"


def test_strict_mode_requires_actor_identity_fields() -> None:
    app = create_app(_settings())
    client = TestClient(app)

    response = client.post(
        "/v1/evaluate",
        json={
            "action_type": "approve_vendor_payment",
            "strict_require_allow": True,
            "attributes": {"vendor_verified": False},
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"]
    assert "actor_id" in str(body["error"]["details"])
    assert "actor_role" in str(body["error"]["details"])


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
    assert skipped.json()["error"]["code"] == "promotion_validation_failed"

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
    assert response.json()["error"]["code"] == "webhook_mapping_not_configured"


def test_jira_webhook_happy_path_returns_machine_readable_payload() -> None:
    app = create_app(
        _settings(jira_mapping_config_path="src/sena/examples/integrations/jira_mappings.yaml")
    )
    client = TestClient(app)
    payload = {
        "webhookEvent": "jira:issue_updated",
        "timestamp": 1711982000,
        "issue": {
            "id": "10001",
            "key": "RISK-9",
            "fields": {
                "customfield_approval_amount": 25000,
                "customfield_requester_role": "finance_analyst",
                "customfield_vendor_verified": False,
            },
        },
        "user": {"accountId": "acct-99"},
        "changelog": {"items": [{"field": "status", "toString": "Pending Approval"}]},
    }

    response = client.post(
        "/v1/integrations/jira/webhook",
        json=payload,
        headers={"x-atlassian-webhook-identifier": "jira-delivery-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "evaluated"
    assert body["mapped_action_proposal"]["request_id"] == "RISK-9"
    assert body["decision"]["decision_id"].startswith("dec_")


def test_jira_webhook_duplicate_delivery_returns_stable_duplicate_response() -> None:
    app = create_app(
        _settings(jira_mapping_config_path="src/sena/examples/integrations/jira_mappings.yaml")
    )
    client = TestClient(app)
    payload = {
        "webhookEvent": "jira:issue_updated",
        "timestamp": 1711982000,
        "issue": {
            "id": "10001",
            "key": "RISK-9",
            "fields": {
                "customfield_approval_amount": 25000,
                "customfield_requester_role": "finance_analyst",
                "customfield_vendor_verified": False,
            },
        },
        "user": {"accountId": "acct-99"},
        "changelog": {"items": [{"field": "status", "toString": "Pending Approval"}]},
    }
    headers = {"x-atlassian-webhook-identifier": "jira-delivery-dup"}

    first = client.post("/v1/integrations/jira/webhook", json=payload, headers=headers)
    second = client.post("/v1/integrations/jira/webhook", json=payload, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate_ignored"
    assert second.json()["error"]["code"] == "jira_duplicate_delivery"


def test_jira_webhook_missing_actor_identity_returns_deterministic_error() -> None:
    app = create_app(
        _settings(jira_mapping_config_path="src/sena/examples/integrations/jira_mappings.yaml")
    )
    client = TestClient(app)
    payload = {
        "webhookEvent": "jira:issue_updated",
        "timestamp": 1711982000,
        "issue": {
            "id": "10001",
            "key": "RISK-9",
            "fields": {
                "customfield_approval_amount": 25000,
                "customfield_requester_role": "finance_analyst",
                "customfield_vendor_verified": False,
            },
        },
        "user": {"displayName": "No account id"},
        "changelog": {"items": [{"field": "status", "toString": "Pending Approval"}]},
    }

    response = client.post(
        "/v1/integrations/jira/webhook",
        json=payload,
        headers={"x-atlassian-webhook-identifier": "jira-delivery-actor-missing"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "jira_missing_required_fields"


def test_jira_webhook_unsupported_event_returns_deterministic_error() -> None:
    app = create_app(
        _settings(jira_mapping_config_path="src/sena/examples/integrations/jira_mappings.yaml")
    )
    client = TestClient(app)
    response = client.post(
        "/v1/integrations/jira/webhook",
        json={"webhookEvent": "jira:comment_created", "issue": {"id": "100", "key": "RISK-2"}},
        headers={"x-atlassian-webhook-identifier": "jira-delivery-unsupported"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "jira_unsupported_event_type"


def test_rate_limiting_per_api_key() -> None:
    app = create_app(
        _settings(enable_api_key_auth=True, api_key="secret", rate_limit_requests=1, rate_limit_window_seconds=60)
    )
    client = TestClient(app)

    first = client.post(
        "/v1/evaluate",
        headers={"x-api-key": "secret"},
        json={"action_type": "approve_vendor_payment", "attributes": {"vendor_verified": False}},
    )
    second = client.post(
        "/v1/evaluate",
        headers={"x-api-key": "secret"},
        json={"action_type": "approve_vendor_payment", "attributes": {"vendor_verified": False}},
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limited"


def test_request_size_limit() -> None:
    app = create_app(_settings(request_max_bytes=128))
    client = TestClient(app)

    response = client.post(
        "/v1/evaluate",
        json={
            "action_type": "approve_vendor_payment",
            "attributes": {"vendor_verified": False, "padding": "x" * 200},
        },
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_timeout_handling_returns_gateway_timeout(monkeypatch) -> None:
    from sena.engine import evaluator as evaluator_module

    app = create_app(_settings(request_timeout_seconds=0.01))
    client = TestClient(app)
    original_evaluate = evaluator_module.PolicyEvaluator.evaluate

    def _slow_evaluate(self, proposal, facts):
        time.sleep(0.05)
        return original_evaluate(self, proposal, facts)

    monkeypatch.setattr(evaluator_module.PolicyEvaluator, "evaluate", _slow_evaluate)

    response = client.post(
        "/v1/evaluate",
        json={"action_type": "approve_vendor_payment", "attributes": {"vendor_verified": False}},
    )

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "timeout"


def test_metrics_endpoint_exposes_prometheus_metrics() -> None:
    app = create_app(_settings())
    client = TestClient(app)

    evaluate_response = client.post(
        "/v1/evaluate",
        json={
            "action_type": "approve_vendor_payment",
            "attributes": {"amount": 15000, "vendor_verified": False},
            "facts": {},
        },
    )
    assert evaluate_response.status_code == 200

    metrics_response = client.get("/metrics")
    assert metrics_response.status_code == 200
    assert "text/plain" in metrics_response.headers["content-type"]
    metrics_body = metrics_response.text
    assert "request_count_total" in metrics_body
    assert "decision_outcome_count_total" in metrics_body
    assert 'decision_outcome_count_total{endpoint="/v1/evaluate",outcome="BLOCKED"}' in metrics_body
    assert 'evaluation_latency_bucket{endpoint="/v1/evaluate",le=' in metrics_body


def test_request_id_header_is_preserved_across_evaluate_flow() -> None:
    app = create_app(_settings())
    client = TestClient(app)

    response = client.post(
        "/v1/evaluate",
        headers={"x-request-id": "req-correlation-123"},
        json={"action_type": "approve_vendor_payment", "attributes": {"vendor_verified": False}},
    )
    assert response.status_code == 200
    body = response.json()
    assert response.headers["x-request-id"] == "req-correlation-123"
    assert body["request_id"] == "req-correlation-123"


def test_startup_fails_when_policy_dir_missing() -> None:
    with pytest.raises(RuntimeError, match="SENA_POLICY_DIR must point to an existing directory"):
        create_app(_settings(policy_dir="does/not/exist"))


def test_startup_fails_when_bundle_has_no_rules(tmp_path) -> None:
    policy_dir = tmp_path / "empty_bundle"
    policy_dir.mkdir()
    (policy_dir / "bundle.yaml").write_text("bundle_name: enterprise-demo\nversion: 2026.03\n")

    with pytest.raises(RuntimeError, match="Failed to load policy bundle: no policy files were found"):
        create_app(_settings(policy_dir=str(policy_dir)))


def test_startup_fails_when_api_key_set_but_disabled() -> None:
    with pytest.raises(RuntimeError, match="SENA_API_KEY is set but SENA_API_KEY_ENABLED is not true"):
        create_app(_settings(enable_api_key_auth=False, api_key="secret"))


def test_startup_fails_in_production_without_api_key_auth() -> None:
    with pytest.raises(RuntimeError, match="SENA_RUNTIME_MODE=production requires SENA_API_KEY_ENABLED=true"):
        create_app(_settings(runtime_mode="production", enable_api_key_auth=False))


def test_startup_fails_when_api_keys_has_invalid_role() -> None:
    with pytest.raises(RuntimeError, match="unsupported role"):
        create_app(_settings(enable_api_key_auth=True, api_keys=(("key-1", "reader"),)))
