import json
from pathlib import Path

import pytest
import time
from datetime import datetime

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
        "promotion_gate_require_validation_artifact": True,
        "promotion_gate_require_simulation": True,
        "promotion_gate_required_scenario_ids": (),
        "promotion_gate_max_changed_outcomes": None,
        "promotion_gate_max_regressions_by_outcome_type": (),
        "promotion_gate_break_glass_enabled": True,
    }
    defaults.update(kwargs)
    return ApiSettings(**defaults)


def _servicenow_fixture(name: str) -> dict:
    fixture_path = Path("tests/fixtures/integrations/servicenow") / f"{name}.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


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

    evaluate_response = client.post(
        "/evaluate", json={"action_type": "approve_vendor_payment"}
    )
    assert evaluate_response.status_code == 410
    assert evaluate_response.json()["error"]["code"] == "route_deprecated"
    assert "/v1/evaluate" in evaluate_response.json()["error"]["message"]


def test_readiness_endpoint() -> None:
    app = create_app(_settings())
    client = TestClient(app)

    response = client.get("/v1/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["mode"] == "development"


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


def test_audit_verify_tree_endpoint(tmp_path) -> None:
    from sena.audit.merkle import build_merkle_tree, get_proof

    audit_path = tmp_path / "audit.jsonl"
    app = create_app(_settings(audit_sink_jsonl=str(audit_path)))
    client = TestClient(app)

    first = client.post(
        "/v1/evaluate",
        json={
            "action_type": "approve_vendor_payment",
            "attributes": {"vendor_verified": False},
        },
    )
    second = client.post(
        "/v1/evaluate",
        json={
            "action_type": "approve_vendor_payment",
            "attributes": {"vendor_verified": True},
        },
    )
    assert first.status_code == 200
    assert second.status_code == 200

    entries = [json.loads(line) for line in audit_path.read_text().splitlines() if line]
    tree = build_merkle_tree(entries)
    target_decision_id = second.json()["decision_id"]
    target_index = next(
        idx
        for idx, entry in enumerate(entries)
        if entry.get("decision_id") == target_decision_id
    )
    proof = get_proof(tree, target_index)

    response = client.post(
        "/v1/audit/verify/tree",
        json={
            "decision_id": target_decision_id,
            "merkle_proof": proof,
            "expected_root": tree.root,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is True
    assert payload["proof_matches_canonical"] is True
    assert payload["computed_root"] == tree.root


def test_audit_verify_tree_endpoint_returns_invalid_for_wrong_root(tmp_path) -> None:
    from sena.audit.merkle import build_merkle_tree, get_proof

    audit_path = tmp_path / "audit.jsonl"
    app = create_app(_settings(audit_sink_jsonl=str(audit_path)))
    client = TestClient(app)

    evaluate = client.post(
        "/v1/evaluate",
        json={
            "action_type": "approve_vendor_payment",
            "attributes": {"vendor_verified": False},
        },
    )
    assert evaluate.status_code == 200

    entries = [json.loads(line) for line in audit_path.read_text().splitlines() if line]
    tree = build_merkle_tree(entries)
    decision_id = evaluate.json()["decision_id"]
    proof = get_proof(tree, 0)

    response = client.post(
        "/v1/audit/verify/tree",
        json={
            "decision_id": decision_id,
            "merkle_proof": proof,
            "expected_root": "00" * 32,
        },
    )

    assert response.status_code == 200
    assert response.json()["valid"] is False


def test_evaluate_review_package_endpoint_returns_durable_artifact() -> None:
    app = create_app(_settings())
    client = TestClient(app)

    response = client.post(
        "/v1/evaluate/review-package",
        json={
            "action_type": "approve_vendor_payment",
            "request_id": "req-api-review",
            "actor_id": "actor-api",
            "actor_role": "finance_analyst",
            "attributes": {
                "amount": 15000,
                "vendor_verified": False,
                "requester_role": "finance_analyst",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["package_type"] == "sena.decision_review_package"
    assert body["decision_summary"]["outcome"] == "BLOCKED"
    assert body["precedence"]["explanation"]
    assert body["policy_bundle_metadata"]["bundle_name"] == "enterprise-demo"


def test_api_key_auth_blocks_unauthorized_request() -> None:
    app = create_app(_settings(enable_api_key_auth=True, api_key="secret"))
    client = TestClient(app)

    response = client.post(
        "/v1/evaluate", json={"action_type": "approve_vendor_payment"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_api_key_auth_allows_authorized_request() -> None:
    app = create_app(_settings(enable_api_key_auth=True, api_key="secret"))
    client = TestClient(app)

    response = client.post(
        "/v1/evaluate",
        headers={"x-api-key": "secret"},
        json={
            "action_type": "approve_vendor_payment",
            "attributes": {"vendor_verified": False},
        },
    )
    assert response.status_code == 200


def test_api_key_role_evaluator_cannot_promote_bundle() -> None:
    app = create_app(
        _settings(enable_api_key_auth=True, api_keys=(("eval-key", "evaluator"),))
    )
    client = TestClient(app)

    response = client.post(
        "/v1/bundle/promote",
        headers={"x-api-key": "eval-key"},
        json={
            "bundle_id": 1,
            "target_lifecycle": "active",
            "promoted_by": "u",
            "promotion_reason": "r",
            "validation_artifact": "a",
        },
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
        json={
            "items": [
                {
                    "action_type": "approve_vendor_payment",
                    "attributes": {"vendor_verified": False},
                }
            ]
        },
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
                    "source_system": "jira",
                    "workflow_stage": "pending_approval",
                    "risk_category": "vendor_payment",
                    "attributes": {"vendor_verified": False},
                    "facts": {},
                }
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["total_scenarios"] == 1
    assert response.json()["grouped_changes"]["source_system"]["jira"]["total"] == 1


def test_replay_drift_endpoint() -> None:
    app = create_app(_settings())
    client = TestClient(app)
    response = client.post(
        "/v1/replay/drift",
        json={
            "baseline_policy_dir": "src/sena/examples/policies",
            "candidate_policy_dir": "src/sena/examples/policies",
            "replay_payload": {
                "cases": [
                    {
                        "case_id": "api-replay-1",
                        "proposal": {
                            "action_type": "approve_vendor_payment",
                            "request_id": "api-r1",
                            "actor_id": "actor-api",
                            "actor_role": "finance_analyst",
                            "attributes": {
                                "amount": 250,
                                "vendor_verified": True,
                                "source_system": "jira",
                            },
                            "action_origin": "human",
                        },
                        "facts": {},
                    }
                ]
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["replay_type"] == "sena.ai_workflow_drift"
    assert body["changed_outcomes"] == 0


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
        json={
            "action_type": "approve_vendor_payment",
            "attributes": {"vendor_verified": False},
        },
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
        json={
            "bundle_id": bundle_id,
            "target_lifecycle": "active",
            "promoted_by": "ops",
            "promotion_reason": "go",
            "validation_artifact": "CAB",
        },
    )
    assert skipped.status_code == 400
    assert skipped.json()["error"]["code"] == "promotion_validation_failed"

    to_candidate = client.post(
        "/v1/bundle/promote",
        json={
            "bundle_id": bundle_id,
            "target_lifecycle": "candidate",
            "promoted_by": "ops",
            "promotion_reason": "ready",
        },
    )
    assert to_candidate.status_code == 200


def test_active_promotion_passes_with_validation_and_simulation_evidence(
    tmp_path,
) -> None:
    from sena.policy.parser import load_policy_bundle
    from sena.policy.store import SQLitePolicyBundleRepository

    db_path = tmp_path / "policy_registry.db"
    repo = SQLitePolicyBundleRepository(str(db_path))
    repo.initialize()
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    metadata.lifecycle = "draft"
    baseline_id = repo.register_bundle(metadata, rules)
    repo.transition_bundle(
        baseline_id, "candidate", promoted_by="ops", promotion_reason="ready"
    )
    repo.transition_bundle(
        baseline_id,
        "active",
        promoted_by="ops",
        promotion_reason="go",
        validation_artifact="CAB-1",
        evidence_json='{"simulation":"ok"}',
    )

    metadata.version = "2026.99"
    metadata.lifecycle = "draft"
    candidate_id = repo.register_bundle(metadata, rules)
    repo.transition_bundle(
        candidate_id, "candidate", promoted_by="ops", promotion_reason="ready"
    )

    app = create_app(
        _settings(
            policy_store_backend="sqlite",
            policy_store_sqlite_path=str(db_path),
            bundle_name=metadata.bundle_name,
        )
    )
    client = TestClient(app)
    response = client.post(
        "/v1/bundle/promote",
        json={
            "bundle_id": candidate_id,
            "target_lifecycle": "active",
            "promoted_by": "ops",
            "promotion_reason": "go",
            "validation_artifact": "CAB-2",
            "simulation_result": {
                "changed_scenarios": 0,
                "changes": [
                    {
                        "scenario_id": "s1",
                        "before_outcome": "BLOCKED",
                        "after_outcome": "BLOCKED",
                    }
                ],
            },
        },
    )
    assert response.status_code == 200


def test_active_promotion_threshold_failure_and_break_glass_history(tmp_path) -> None:
    from sena.policy.parser import load_policy_bundle
    from sena.policy.store import SQLitePolicyBundleRepository

    db_path = tmp_path / "policy_registry.db"
    repo = SQLitePolicyBundleRepository(str(db_path))
    repo.initialize()
    rules, metadata = load_policy_bundle("src/sena/examples/policies")

    metadata.lifecycle = "draft"
    baseline_id = repo.register_bundle(metadata, rules)
    repo.transition_bundle(
        baseline_id, "candidate", promoted_by="ops", promotion_reason="ready"
    )
    repo.transition_bundle(
        baseline_id,
        "active",
        promoted_by="ops",
        promotion_reason="go",
        validation_artifact="CAB-1",
        evidence_json='{"simulation":"ok"}',
    )

    metadata.version = "2026.05"
    metadata.lifecycle = "draft"
    candidate_id = repo.register_bundle(metadata, rules)
    repo.transition_bundle(
        candidate_id, "candidate", promoted_by="ops", promotion_reason="ready"
    )

    app = create_app(
        _settings(
            policy_store_backend="sqlite",
            policy_store_sqlite_path=str(db_path),
            bundle_name=metadata.bundle_name,
        )
    )
    client = TestClient(app)

    threshold_fail = client.post(
        "/v1/bundle/promote",
        json={
            "bundle_id": candidate_id,
            "target_lifecycle": "active",
            "promoted_by": "ops",
            "promotion_reason": "go",
            "validation_artifact": "CAB-2",
            "simulation_result": {
                "changed_scenarios": 3,
                "grouped_changes": {
                    "risk_category": {"vendor_payment": {"changed": 2}}
                },
                "changes": [{"before_outcome": "BLOCKED", "after_outcome": "APPROVED"}],
            },
            "thresholds": {
                "max_changed_outcomes": 1,
                "max_block_to_approve_regressions": 0,
                "max_changed_risk_categories": {"vendor_payment": 0},
            },
        },
    )
    assert threshold_fail.status_code == 400
    assert threshold_fail.json()["error"]["code"] == "promotion_validation_failed"
    assert threshold_fail.json()["error"]["details"]["failures"]

    break_glass = client.post(
        "/v1/bundle/promote",
        json={
            "bundle_id": candidate_id,
            "target_lifecycle": "active",
            "promoted_by": "ops",
            "promotion_reason": "incident override",
            "break_glass": True,
            "break_glass_reason": "SEV-1 mitigation",
        },
    )
    assert break_glass.status_code == 200

    history = client.get(
        "/v1/bundles/history", params={"bundle_name": metadata.bundle_name}
    ).json()["history"]
    latest = history[0]
    assert latest["action"] == "promote_break_glass"
    assert latest["break_glass"] == 1
    assert latest["audit_marker"] == "break_glass_promotion"
    assert latest["policy_diff_summary"] is not None
    assert latest["evidence_json"] is not None


def test_active_promotion_fails_without_any_evidence(tmp_path) -> None:
    from sena.policy.parser import load_policy_bundle
    from sena.policy.store import SQLitePolicyBundleRepository

    db_path = tmp_path / "policy_registry.db"
    repo = SQLitePolicyBundleRepository(str(db_path))
    repo.initialize()
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    metadata.lifecycle = "draft"
    bundle_id = repo.register_bundle(metadata, rules)
    repo.transition_bundle(
        bundle_id, "candidate", promoted_by="ops", promotion_reason="ready"
    )

    app = create_app(
        _settings(
            policy_store_backend="sqlite",
            policy_store_sqlite_path=str(db_path),
            bundle_name=metadata.bundle_name,
        )
    )
    client = TestClient(app)
    response = client.post(
        "/v1/bundle/promote",
        json={
            "bundle_id": bundle_id,
            "target_lifecycle": "active",
            "promoted_by": "ops",
            "promotion_reason": "go",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "promotion_validation_failed"
    failures = response.json()["error"]["details"]["failures"]
    assert any(item["code"] == "missing_simulation_report" for item in failures)


def test_active_promotion_is_idempotent_when_already_active(tmp_path) -> None:
    from sena.policy.parser import load_policy_bundle
    from sena.policy.store import SQLitePolicyBundleRepository

    db_path = tmp_path / "policy_registry.db"
    repo = SQLitePolicyBundleRepository(str(db_path))
    repo.initialize()
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    metadata.lifecycle = "draft"
    bundle_id = repo.register_bundle(metadata, rules)
    repo.transition_bundle(
        bundle_id, "candidate", promoted_by="ops", promotion_reason="ready"
    )

    app = create_app(
        _settings(
            policy_store_backend="sqlite",
            policy_store_sqlite_path=str(db_path),
            bundle_name=metadata.bundle_name,
        )
    )
    client = TestClient(app)
    first = client.post(
        "/v1/bundle/promote",
        json={
            "bundle_id": bundle_id,
            "target_lifecycle": "active",
            "promoted_by": "ops",
            "promotion_reason": "go",
            "validation_artifact": "CAB-1",
            "simulation_result": {
                "changed_scenarios": 0,
                "changes": [
                    {
                        "scenario_id": "s1",
                        "before_outcome": "BLOCKED",
                        "after_outcome": "BLOCKED",
                    }
                ],
            },
        },
    )
    assert first.status_code == 200
    second = client.post(
        "/v1/bundle/promote",
        json={
            "bundle_id": bundle_id,
            "target_lifecycle": "active",
            "promoted_by": "ops",
            "promotion_reason": "go-again",
        },
    )
    assert second.status_code == 200
    assert second.json()["idempotent"] is True


def test_register_bundle_fails_when_signature_strict_and_manifest_invalid(
    tmp_path,
) -> None:
    policy_dir = tmp_path / "bundle"
    policy_dir.mkdir()
    (policy_dir / "bundle.yaml").write_text(
        "bundle_name: strict-demo\nversion: 1.0.0\n"
    )
    (policy_dir / "rules.yaml").write_text(
        '[{"id":"r1","description":"d","severity":"low","inviolable":false,"applies_to":["a"],"condition":{"field":"x","eq":1},"decision":"BLOCK","reason":"ok"}]'
    )
    (policy_dir / "release-manifest.json").write_text("{}")
    db_path = tmp_path / "policy_registry.db"

    app = create_app(
        _settings(
            policy_store_backend="sqlite",
            policy_store_sqlite_path=str(db_path),
            bundle_name="strict-demo",
            bundle_signature_strict=True,
            bundle_signature_keyring_dir=str(tmp_path / "keyring"),
        )
    )
    client = TestClient(app)
    response = client.post(
        "/v1/bundle/register",
        json={
            "policy_dir": str(policy_dir),
            "bundle_name": "strict-demo",
            "bundle_version": "1.0.0",
            "lifecycle": "draft",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bundle_signature_verification_failed"


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
                            "requested_by": "user_9",
                        },
                    }
                },
            },
            "facts": {},
        },
    )

    assert response.status_code == 200
    assert response.headers["x-sena-surface-stage"] == "experimental"
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
        json={
            "provider": "stripe",
            "event_type": "payment_intent.created",
            "payload": {},
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "webhook_mapping_not_configured"


def test_jira_webhook_happy_path_returns_machine_readable_payload() -> None:
    app = create_app(
        _settings(
            jira_mapping_config_path="src/sena/examples/integrations/jira_mappings.yaml"
        )
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
        _settings(
            jira_mapping_config_path="src/sena/examples/integrations/jira_mappings.yaml"
        )
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
    assert second.json()["error"]["request_id"].startswith("req_")
    datetime.fromisoformat(second.json()["error"]["timestamp"])


def test_jira_webhook_missing_actor_identity_returns_deterministic_error() -> None:
    app = create_app(
        _settings(
            jira_mapping_config_path="src/sena/examples/integrations/jira_mappings.yaml"
        )
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
        _settings(
            jira_mapping_config_path="src/sena/examples/integrations/jira_mappings.yaml"
        )
    )
    client = TestClient(app)
    response = client.post(
        "/v1/integrations/jira/webhook",
        json={
            "webhookEvent": "jira:comment_created",
            "issue": {"id": "100", "key": "RISK-2"},
        },
        headers={"x-atlassian-webhook-identifier": "jira-delivery-unsupported"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "jira_unsupported_event_type"


def test_servicenow_webhook_happy_path_returns_machine_readable_payload() -> None:
    app = create_app(
        _settings(
            servicenow_mapping_config_path="src/sena/examples/integrations/servicenow_mappings.yaml"
        )
    )
    client = TestClient(app)
    payload = _servicenow_fixture("emergency_change")

    response = client.post(
        "/v1/integrations/servicenow/webhook",
        json=payload,
        headers={"x-servicenow-delivery-id": "sn-delivery-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "evaluated"
    assert body["normalized_event"]["source_system"] == "servicenow"
    assert (
        body["mapped_action_proposal"]["request_id"]
        == payload["change_request"]["number"]
    )


def test_servicenow_webhook_duplicate_delivery_returns_stable_duplicate_response() -> (
    None
):
    app = create_app(
        _settings(
            servicenow_mapping_config_path="src/sena/examples/integrations/servicenow_mappings.yaml"
        )
    )
    client = TestClient(app)
    payload = _servicenow_fixture("emergency_change")
    headers = {"x-servicenow-delivery-id": "sn-delivery-dup"}

    first = client.post(
        "/v1/integrations/servicenow/webhook", json=payload, headers=headers
    )
    second = client.post(
        "/v1/integrations/servicenow/webhook", json=payload, headers=headers
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate_ignored"
    assert second.json()["error"]["code"] == "servicenow_duplicate_delivery"
    assert second.json()["error"]["request_id"].startswith("req_")
    datetime.fromisoformat(second.json()["error"]["timestamp"])


def test_webhook_endpoint_rejects_unknown_provider_fail_closed() -> None:
    app = create_app(
        _settings(
            webhook_mapping_config_path="src/sena/examples/integrations/webhook_mappings.yaml"
        )
    )
    client = TestClient(app)

    response = client.post(
        "/v1/integrations/webhook",
        json={
            "provider": "unknown-provider",
            "event_type": "payment_intent.created",
            "payload": {"id": "evt-1"},
            "facts": {},
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "webhook_mapping_error"
    assert "Unknown webhook provider" in body["error"]["details"]["reason"]


def test_servicenow_webhook_missing_actor_identity_returns_deterministic_error() -> (
    None
):
    app = create_app(
        _settings(
            servicenow_mapping_config_path="src/sena/examples/integrations/servicenow_mappings.yaml"
        )
    )
    client = TestClient(app)
    payload = _servicenow_fixture("emergency_change")
    del payload["requested_by"]["user_id"]

    response = client.post(
        "/v1/integrations/servicenow/webhook",
        json=payload,
        headers={"x-servicenow-delivery-id": "sn-delivery-missing-user"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "servicenow_missing_required_fields"


def test_servicenow_webhook_audit_record_includes_source_metadata() -> None:
    app = create_app(
        _settings(
            servicenow_mapping_config_path="src/sena/examples/integrations/servicenow_mappings.yaml"
        )
    )
    client = TestClient(app)
    payload = _servicenow_fixture("privileged_change")

    response = client.post(
        "/v1/integrations/servicenow/webhook",
        json=payload,
        headers={"x-servicenow-delivery-id": "sn-delivery-audit"},
    )

    assert response.status_code == 200
    source_metadata = response.json()["decision"]["audit_record"]["source_metadata"]
    assert source_metadata["source_system"] == "servicenow"
    assert source_metadata["source_event_type"] == "change_approval.requested"
    assert (
        source_metadata["servicenow_change_number"]
        == payload["change_request"]["number"]
    )


def test_rate_limiting_per_api_key() -> None:
    app = create_app(
        _settings(
            enable_api_key_auth=True,
            api_key="secret",
            rate_limit_requests=1,
            rate_limit_window_seconds=60,
        )
    )
    client = TestClient(app)

    first = client.post(
        "/v1/evaluate",
        headers={"x-api-key": "secret"},
        json={
            "action_type": "approve_vendor_payment",
            "attributes": {"vendor_verified": False},
        },
    )
    second = client.post(
        "/v1/evaluate",
        headers={"x-api-key": "secret"},
        json={
            "action_type": "approve_vendor_payment",
            "attributes": {"vendor_verified": False},
        },
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
        json={
            "action_type": "approve_vendor_payment",
            "attributes": {"vendor_verified": False},
        },
    )

    assert response.status_code == 504
    body = response.json()
    assert body["error"]["code"] == "timeout"
    assert body["error"]["request_id"].startswith("req_")
    datetime.fromisoformat(body["error"]["timestamp"])


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

    metrics_response = client.get("/v1/metrics/prometheus")
    assert metrics_response.status_code == 200
    assert "text/plain" in metrics_response.headers["content-type"]
    metrics_body = metrics_response.text
    assert "request_count_total" in metrics_body
    assert "sena_decisions_total" in metrics_body
    assert (
        'sena_decisions_total{outcome="BLOCKED"} 1.0' in metrics_body
    )
    assert "sena_evaluation_seconds_bucket" in metrics_body
    assert "sena_audit_entries_total" in metrics_body
    assert "sena_merkle_root_timestamp" in metrics_body

    verify_response = client.post(
        "/v1/audit/verify/tree",
        json={
            "decision_id": evaluate_response.json()["decision_id"],
            "merkle_proof": ["not-a-real-proof"],
            "expected_root": "invalid-root",
        },
    )
    assert verify_response.status_code == 200
    assert verify_response.json()["valid"] is False

    metrics_after_verify = client.get("/v1/metrics/prometheus")
    assert metrics_after_verify.status_code == 200
    assert "sena_verification_requests_total 1.0" in metrics_after_verify.text
    assert "sena_verification_failures_total 1.0" in metrics_after_verify.text


def test_request_id_header_is_preserved_across_evaluate_flow() -> None:
    app = create_app(_settings())
    client = TestClient(app)

    response = client.post(
        "/v1/evaluate",
        headers={"x-request-id": "req-correlation-123"},
        json={
            "action_type": "approve_vendor_payment",
            "attributes": {"vendor_verified": False},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert response.headers["x-request-id"] == "req-correlation-123"
    assert body["request_id"] == "req-correlation-123"


def test_startup_fails_when_policy_dir_missing() -> None:
    with pytest.raises(
        RuntimeError, match="SENA_POLICY_DIR must point to an existing directory"
    ):
        create_app(_settings(policy_dir="does/not/exist"))


def test_startup_fails_when_bundle_has_no_rules(tmp_path) -> None:
    policy_dir = tmp_path / "empty_bundle"
    policy_dir.mkdir()
    (policy_dir / "bundle.yaml").write_text(
        "bundle_name: enterprise-demo\nversion: 2026.03\n"
    )

    with pytest.raises(
        RuntimeError, match="Failed to load policy bundle: no policy files were found"
    ):
        create_app(_settings(policy_dir=str(policy_dir)))


def test_startup_fails_when_api_key_set_but_disabled() -> None:
    with pytest.raises(
        RuntimeError, match="SENA_API_KEY is set but SENA_API_KEY_ENABLED is not true"
    ):
        create_app(_settings(enable_api_key_auth=False, api_key="secret"))


def test_startup_fails_in_production_without_api_key_auth() -> None:
    with pytest.raises(
        RuntimeError,
        match="SENA_RUNTIME_MODE=production requires SENA_API_KEY_ENABLED=true",
    ):
        create_app(_settings(runtime_mode="production", enable_api_key_auth=False))


def test_startup_fails_when_api_keys_has_invalid_role() -> None:
    with pytest.raises(RuntimeError, match="unsupported role"):
        create_app(_settings(enable_api_key_auth=True, api_keys=(("key-1", "reader"),)))


def test_startup_fails_when_runtime_mode_is_invalid() -> None:
    with pytest.raises(RuntimeError, match="SENA_RUNTIME_MODE must be one of"):
        create_app(_settings(runtime_mode="prod"))


def test_startup_fails_when_sqlite_store_path_missing() -> None:
    with pytest.raises(RuntimeError, match="SENA_POLICY_STORE_SQLITE_PATH is required"):
        create_app(
            _settings(policy_store_backend="sqlite", policy_store_sqlite_path=None)
        )


def test_startup_fails_when_slack_is_partially_configured() -> None:
    with pytest.raises(RuntimeError, match="must be set together"):
        create_app(_settings(slack_bot_token="xoxb-test", slack_channel=None))


def test_startup_fails_when_integration_mapping_path_missing() -> None:
    with pytest.raises(
        RuntimeError, match="SENA_JIRA_MAPPING_CONFIG must point to an existing file"
    ):
        create_app(_settings(jira_mapping_config_path="does/not/exist.yaml"))


def test_startup_fails_in_production_without_audit_sink() -> None:
    with pytest.raises(RuntimeError, match="requires SENA_AUDIT_SINK_JSONL"):
        create_app(
            _settings(
                runtime_mode="production",
                enable_api_key_auth=True,
                api_key="secret",
            )
        )


def test_startup_fails_when_strict_audit_verification_enabled_without_sink() -> None:
    with pytest.raises(
        RuntimeError,
        match="SENA_AUDIT_VERIFY_ON_STARTUP_STRICT=true requires SENA_AUDIT_SINK_JSONL",
    ):
        create_app(
            _settings(audit_verify_on_startup_strict=True, audit_sink_jsonl=None)
        )


def test_startup_fails_when_strict_audit_verification_detects_corruption(
    tmp_path,
) -> None:
    audit_path = tmp_path / "audit.jsonl"
    audit_path.write_text('{"decision_id":"broken"')
    with pytest.raises(RuntimeError, match="Startup audit verification failed"):
        create_app(
            _settings(
                audit_verify_on_startup_strict=True,
                audit_sink_jsonl=str(audit_path),
            )
        )


def test_startup_fails_in_production_without_signature_strictness(tmp_path) -> None:
    keyring_dir = tmp_path / "keyring"
    keyring_dir.mkdir()
    with pytest.raises(
        RuntimeError, match="requires SENA_BUNDLE_SIGNATURE_STRICT=true"
    ):
        create_app(
            _settings(
                runtime_mode="production",
                enable_api_key_auth=True,
                api_key="secret",
                audit_sink_jsonl=str(tmp_path / "audit.jsonl"),
                bundle_signature_strict=False,
                bundle_signature_keyring_dir=str(keyring_dir),
            )
        )


def test_startup_fails_in_production_without_jira_secret(tmp_path) -> None:
    mapping_path = tmp_path / "jira-mapping.json"
    mapping_path.write_text(
        json.dumps(
            {
                "routes": {
                    "jira:issue_updated": {
                        "action_type": "approve_vendor_payment",
                        "actor_id_path": "user.accountId",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    keyring_dir = tmp_path / "keyring"
    keyring_dir.mkdir()
    with pytest.raises(RuntimeError, match="requires SENA_JIRA_WEBHOOK_SECRET"):
        create_app(
            _settings(
                runtime_mode="production",
                enable_api_key_auth=True,
                api_key="secret",
                audit_sink_jsonl=str(tmp_path / "audit.jsonl"),
                bundle_signature_strict=True,
                bundle_signature_keyring_dir=str(keyring_dir),
                jira_mapping_config_path=str(mapping_path),
                jira_webhook_secret=None,
            )
        )


def test_bundle_history_by_version_and_rollback_endpoints(tmp_path) -> None:
    from sena.policy.parser import load_policy_bundle
    from sena.policy.store import SQLitePolicyBundleRepository

    db_path = tmp_path / "policy_registry.db"
    repo = SQLitePolicyBundleRepository(str(db_path))
    repo.initialize()
    rules, metadata = load_policy_bundle("src/sena/examples/policies")

    metadata.lifecycle = "draft"
    id1 = repo.register_bundle(metadata, rules)
    repo.transition_bundle(
        id1, "candidate", promoted_by="ops", promotion_reason="ready"
    )
    repo.transition_bundle(
        id1,
        "active",
        promoted_by="ops",
        promotion_reason="go",
        validation_artifact="CAB-1",
        evidence_json='{"simulation":"ok"}',
    )

    metadata.version = "2026.04"
    metadata.lifecycle = "draft"
    id2 = repo.register_bundle(metadata, rules)
    repo.transition_bundle(
        id2, "candidate", promoted_by="ops", promotion_reason="ready"
    )
    repo.transition_bundle(
        id2,
        "active",
        promoted_by="ops",
        promotion_reason="go",
        validation_artifact="CAB-2",
        evidence_json='{"simulation":"ok"}',
    )

    app = create_app(
        _settings(
            policy_store_backend="sqlite",
            policy_store_sqlite_path=str(db_path),
            bundle_name=metadata.bundle_name,
        )
    )
    client = TestClient(app)

    history = client.get(
        "/v1/bundles/history", params={"bundle_name": metadata.bundle_name}
    )
    assert history.status_code == 200
    assert history.json()["history"]

    by_version = client.get(
        "/v1/bundles/by-version",
        params={"bundle_name": metadata.bundle_name, "version": "2026.04"},
    )
    assert by_version.status_code == 200
    assert by_version.json()["bundle_id"] == id2

    rollback = client.post(
        "/v1/bundle/rollback",
        json={
            "bundle_name": metadata.bundle_name,
            "to_bundle_id": id1,
            "promoted_by": "ops",
            "promotion_reason": "incident",
            "validation_artifact": "INC-1",
        },
    )
    assert rollback.status_code == 200

    active = client.get(
        "/v1/bundles/active", params={"bundle_name": metadata.bundle_name}
    )
    assert active.status_code == 200
    assert active.json()["bundle_id"] == id1


def test_bundle_promote_invalid_transition_returns_machine_readable_failure(
    tmp_path,
) -> None:
    from sena.policy.parser import load_policy_bundle
    from sena.policy.store import SQLitePolicyBundleRepository

    db_path = tmp_path / "policy_registry.db"
    repo = SQLitePolicyBundleRepository(str(db_path))
    repo.initialize()
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    metadata.lifecycle = "active"
    active_id = repo.register_bundle(metadata, rules)

    app = create_app(
        _settings(
            policy_store_backend="sqlite",
            policy_store_sqlite_path=str(db_path),
            bundle_name=metadata.bundle_name,
        )
    )
    client = TestClient(app)
    response = client.post(
        "/v1/bundle/promote",
        json={
            "bundle_id": active_id,
            "target_lifecycle": "draft",
            "promoted_by": "ops",
            "promotion_reason": "attempt-invalid-transition",
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "promotion_validation_failed"
    assert "invalid lifecycle transition" in body["error"]["details"]["errors"][0]


def test_bundle_rollback_target_not_found_returns_machine_readable_failure(
    tmp_path,
) -> None:
    from sena.policy.parser import load_policy_bundle
    from sena.policy.store import SQLitePolicyBundleRepository

    db_path = tmp_path / "policy_registry.db"
    repo = SQLitePolicyBundleRepository(str(db_path))
    repo.initialize()
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    metadata.lifecycle = "active"
    repo.register_bundle(metadata, rules)

    app = create_app(
        _settings(
            policy_store_backend="sqlite",
            policy_store_sqlite_path=str(db_path),
            bundle_name=metadata.bundle_name,
        )
    )
    client = TestClient(app)
    response = client.post(
        "/v1/bundle/rollback",
        json={
            "bundle_name": metadata.bundle_name,
            "to_bundle_id": 9999,
            "promoted_by": "ops",
            "promotion_reason": "rollback-missing",
            "validation_artifact": "CAB-404",
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "promotion_validation_failed"
    assert body["error"]["details"]["errors"] == ["rollback target bundle not found"]
