from __future__ import annotations

import threading

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from sena.api.app import create_app
from sena.api.config import ApiSettings
from sena.audit.chain import verify_audit_chain
from sena.core.models import PolicyBundleMetadata
from sena.integrations.persistence import SQLiteIntegrationReliabilityStore
from sena.policy.parser import load_policy_bundle
from sena.policy.store import SQLitePolicyBundleRepository
from sena.services.audit_service import AuditService


def _settings(tmp_path):
    return ApiSettings(
        policy_dir="src/sena/examples/policies",
        bundle_name="enterprise-demo",
        bundle_version="2026.03",
        processing_sqlite_path=str(tmp_path / "runtime.db"),
        webhook_mapping_config_path="src/sena/examples/integrations/webhook_mappings.yaml",
    )


def test_same_inbound_delivery_concurrent_is_safely_suppressed(tmp_path) -> None:
    db_path = tmp_path / "integration_reliability.db"
    barrier = threading.Barrier(2)
    results: list[bool] = []
    errors: list[str] = []

    def worker() -> None:
        store = SQLiteIntegrationReliabilityStore(str(db_path))
        barrier.wait()
        try:
            results.append(store.mark_if_new("delivery-concurrent-1"))
        except Exception as exc:  # pragma: no cover - diagnostics
            errors.append(str(exc))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert sorted(results) == [False, True]
    summary = SQLiteIntegrationReliabilityStore(str(db_path)).duplicate_suppression_summary()
    assert summary["inbound"]["seen_total"] == 2
    assert summary["inbound"]["suppressed_total"] == 1


def test_same_api_idempotency_key_with_identical_payload_is_serialized(tmp_path) -> None:
    app = create_app(_settings(tmp_path))
    payload = {
        "action_type": "approve_vendor_payment",
        "attributes": {"vendor_verified": False},
    }
    barrier = threading.Barrier(2)
    responses: list[dict] = []

    def worker() -> None:
        with TestClient(app) as client:
            barrier.wait()
            response = client.post(
                "/v1/evaluate",
                headers={"Idempotency-Key": "idem-concurrent-identical"},
                json=payload,
            )
            responses.append({"status": response.status_code, "body": response.json()})

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert [item["status"] for item in responses] == [200, 200]
    decision_ids = {item["body"]["decision_id"] for item in responses}
    assert len(decision_ids) == 1


def test_same_api_idempotency_key_with_different_payload_conflicts(tmp_path) -> None:
    app = create_app(_settings(tmp_path))
    first_payload = {
        "action_type": "approve_vendor_payment",
        "attributes": {"vendor_verified": False},
    }
    second_payload = {
        "action_type": "approve_vendor_payment",
        "attributes": {"vendor_verified": True},
    }

    with TestClient(app) as client:
        first = client.post(
            "/v1/evaluate",
            headers={"Idempotency-Key": "idem-concurrent-conflict"},
            json=first_payload,
        )
        second = client.post(
            "/v1/evaluate",
            headers={"Idempotency-Key": "idem-concurrent-conflict"},
            json=second_payload,
        )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["details"]["reason"] == "idempotency_key_conflict"


def test_concurrent_audit_appends_preserve_chain_integrity(tmp_path) -> None:
    sink_path = tmp_path / "audit.jsonl"
    service = AuditService(sink_path=str(sink_path))
    barrier = threading.Barrier(8)

    def worker(index: int) -> None:
        barrier.wait()
        service.append_record(
            {
                "decision_id": f"decision-{index}",
                "request_id": f"request-{index}",
                "outcome": "ALLOW",
            }
        )

    threads = [threading.Thread(target=worker, args=(idx,)) for idx in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    verification = verify_audit_chain(str(sink_path))
    assert verification["valid"] is True
    assert verification["records"] == 8


def test_concurrent_promotion_attempts_for_same_bundle_are_idempotent(tmp_path) -> None:
    db_path = tmp_path / "registry.db"
    repo = SQLitePolicyBundleRepository(str(db_path))
    repo.initialize()
    rules, meta = load_policy_bundle("src/sena/examples/policies")
    bundle_id = repo.register_bundle(
        PolicyBundleMetadata(
            bundle_name=meta.bundle_name,
            version="2.0.0",
            loaded_from=meta.loaded_from,
            lifecycle="draft",
        ),
        rules,
    )
    repo.transition_bundle(bundle_id, "candidate", promoted_by="ops", promotion_reason="ready")

    barrier = threading.Barrier(2)
    errors: list[str] = []

    def promote(validation_artifact: str) -> None:
        local_repo = SQLitePolicyBundleRepository(str(db_path))
        barrier.wait()
        try:
            local_repo.transition_bundle(
                bundle_id,
                "active",
                promoted_by="ops",
                promotion_reason="promote",
                validation_artifact=validation_artifact,
                evidence_json='{"simulation":"ok"}',
            )
        except Exception as exc:  # pragma: no cover - diagnostics
            errors.append(str(exc))

    t1 = threading.Thread(target=promote, args=("CAB-1",))
    t2 = threading.Thread(target=promote, args=("CAB-2",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert errors == []
    active = repo.get_active_bundle(meta.bundle_name)
    assert active is not None
    assert active.id == bundle_id
