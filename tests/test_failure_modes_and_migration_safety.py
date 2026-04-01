from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from sena.audit.chain import append_audit_record, verify_audit_chain
from sena.core.enums import DecisionOutcome, RuleDecision, Severity
from sena.core.models import ActionProposal, EvaluatorConfig, PolicyBundleMetadata, PolicyRule
from sena.engine.evaluator import PolicyEvaluator
from sena.integrations.approval import ApprovalEventRoute, build_normalized_approval_event
from sena.integrations.base import IntegrationError
from sena.policy.lifecycle import diff_rule_sets, validate_lifecycle_transition, validate_promotion
from sena.policy.migrations import SQLiteMigrationManager
from sena.policy.parser import PolicyParseError, load_policy_bundle
from sena.policy.store import SQLitePolicyBundleRepository


def test_malformed_policy_bundle_rejected(tmp_path: Path) -> None:
    (tmp_path / "bundle.yaml").write_text("bundle_name: malformed\nversion: 1\nlifecycle: draft\n", encoding="utf-8")
    (tmp_path / "policy.yaml").write_text("{id: not-a-list}", encoding="utf-8")

    with pytest.raises(PolicyParseError, match="must contain a list of rules"):
        load_policy_bundle(tmp_path)


def test_duplicate_rule_ids_make_promotion_invalid() -> None:
    rule = PolicyRule(
        id="duplicate-id",
        description="dup",
        severity=Severity.LOW,
        inviolable=False,
        applies_to=["approve_vendor_payment"],
        condition={"field": "amount", "lt": 100},
        decision=RuleDecision.ALLOW,
        reason="ok",
    )

    result = validate_promotion(
        "candidate",
        "active",
        source_rules=[],
        target_rules=[rule, rule],
        validation_artifact="CAB-77",
    )

    assert result.valid is False
    assert "duplicate rule ids" in " ".join(result.errors)


def test_invalid_lifecycle_transition_has_deterministic_error() -> None:
    result = validate_lifecycle_transition("active", "candidate")
    assert result.valid is False
    assert result.errors == ["invalid lifecycle transition 'active' -> 'candidate'"]


def test_missing_identity_and_no_match_strict_allow_mode_blocks() -> None:
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    evaluator = PolicyEvaluator(
        rules,
        policy_bundle=metadata,
        config=EvaluatorConfig(default_decision=DecisionOutcome.APPROVED, require_allow_match=True),
    )

    trace = evaluator.evaluate(
        ActionProposal(action_type="approve_vendor_payment", actor_id=None, actor_role=None, attributes={"amount": 5}),
        facts={},
    )

    assert trace.outcome == DecisionOutcome.BLOCKED
    assert "actor_id" in trace.missing_fields
    assert "actor_role" in trace.missing_fields
    assert "Strict allow mode" in trace.reasoning.precedence_explanation


def test_conflicting_rules_are_reported_and_block_precedence_applies() -> None:
    rules = [
        PolicyRule(
            id="allow-rule",
            description="allow",
            severity=Severity.LOW,
            inviolable=False,
            applies_to=["act"],
            condition={"field": "x", "eq": 1},
            decision=RuleDecision.ALLOW,
            reason="allow",
        ),
        PolicyRule(
            id="block-rule",
            description="block",
            severity=Severity.HIGH,
            inviolable=False,
            applies_to=["act"],
            condition={"field": "x", "eq": 1},
            decision=RuleDecision.BLOCK,
            reason="block",
        ),
    ]
    evaluator = PolicyEvaluator(rules, policy_bundle=PolicyBundleMetadata(bundle_name="b", version="1", loaded_from="tmp"))

    trace = evaluator.evaluate(ActionProposal(action_type="act", attributes={"x": 1}), facts={})

    assert trace.outcome == DecisionOutcome.BLOCKED
    assert trace.conflicting_rules == ["block-rule"]
    assert "conflicting rules" in trace.reasoning.precedence_explanation.lower()


def test_invalid_integration_payload_reports_missing_required_fields() -> None:
    route = ApprovalEventRoute(
        action_type="approve_vendor_payment",
        actor_id_path="requester.id",
        required_fields=["ticket.id", "requester.id"],
        attributes={"amount": "payment.amount"},
    )

    with pytest.raises(IntegrationError, match="missing required fields: ticket.id,requester.id"):
        build_normalized_approval_event(
            payload={"payment": {"amount": 5}},
            route=route,
            source_event_type="evt",
            idempotency_key="idemp",
            source_system="test",
            default_request_id="req",
            default_source_record_id="src",
            error_cls=IntegrationError,
            default_source_object_type="ticket",
            default_workflow_stage="requested",
            default_requested_action="approve",
            default_correlation_key="corr",
        )


def test_bad_migration_state_duplicate_versions_rejected(tmp_path: Path) -> None:
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    (migration_dir / "001_first.sql").write_text("SELECT 1;", encoding="utf-8")
    (migration_dir / "001_second.sql").write_text("SELECT 2;", encoding="utf-8")

    manager = SQLiteMigrationManager(migration_dir)
    with pytest.raises(ValueError, match="duplicate migration versions"):
        manager.discover()


def test_legacy_storage_state_fixture_migrates_forward(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    sql = Path("tests/fixtures/migrations/storage_states/legacy_registry_v1.sql").read_text(encoding="utf-8")

    with sqlite3.connect(db_path) as conn:
        conn.executescript(sql)

    repo = SQLitePolicyBundleRepository(str(db_path))
    repo.initialize()

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(bundles)")}
        migration_versions = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}

    assert {"release_manifest_path", "signature_verified", "created_by", "integrity_digest"}.issubset(columns)
    assert migration_versions == {1, 2, 3, 4}


def test_legacy_bundle_fixture_can_be_loaded_and_diffed() -> None:
    legacy_rules, legacy_meta = load_policy_bundle("tests/fixtures/migrations/legacy_bundle_v1")
    current_rules, _ = load_policy_bundle("src/sena/examples/policies")

    diff = diff_rule_sets(legacy_rules, current_rules)

    assert legacy_meta.version == "2025.09"
    assert diff.added_rule_ids or diff.changed_rule_ids


def test_invalid_content_length_payload_limit_timeout_and_unauthorized() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from sena.api.app import create_app
    from sena.api.config import ApiSettings

    app = create_app(
        ApiSettings(
            policy_dir="src/sena/examples/policies",
            bundle_name="enterprise-demo",
            bundle_version="2026.03",
            enable_api_key_auth=True,
            api_key="secret",
            api_keys=(),
            audit_sink_jsonl=None,
            request_max_bytes=1024,
            request_timeout_seconds=0.001,
        )
    )
    client = TestClient(app)

    invalid_len = client.post(
        "/v1/evaluate",
        headers={"content-length": "nan", "x-api-key": "secret"},
        content=b"{}",
    )
    assert invalid_len.status_code == 400
    assert invalid_len.json()["error"]["code"] == "invalid_content_length"

    oversized = client.post(
        "/v1/evaluate",
        headers={"x-api-key": "secret"},
        content=b"x" * 2048,
    )
    assert oversized.status_code == 413
    assert oversized.json()["error"]["code"] == "payload_too_large"

    unauthorized = client.post("/v1/evaluate", json={"action_type": "approve_vendor_payment"})
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "unauthorized"

    timeout = client.get("/v1/health")
    assert timeout.status_code in {200, 504}


def test_audit_verification_failure_surface_is_actionable(tmp_path: Path) -> None:
    sink = tmp_path / "audit.jsonl"
    append_audit_record(str(sink), {"decision_id": "1", "outcome": "APPROVED"})
    append_audit_record(str(sink), {"decision_id": "2", "outcome": "BLOCKED"})

    rows = [json.loads(line) for line in sink.read_text(encoding="utf-8").splitlines()]
    rows[1]["previous_chain_hash"] = "tampered"
    sink.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    result = verify_audit_chain(str(sink))
    assert result["valid"] is False
    assert any("previous_chain_hash mismatch" in err for err in result["errors"])
