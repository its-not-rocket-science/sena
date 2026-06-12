import sqlite3
import threading
import time

import pytest

from sena.core.models import PolicyBundleMetadata
from sena.policy.parser import load_policy_bundle
from sena.policy.store import (
    PolicyBundleConflictError,
    PolicyBundleInvalidTransitionError,
    PolicyStoreIntegrityError,
    SQLitePolicyBundleRepository,
)


def test_sqlite_repository_register_activate_history_and_fetch(tmp_path) -> None:
    db_path = tmp_path / "registry.db"
    repo = SQLitePolicyBundleRepository(str(db_path))
    repo.initialize()

    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    metadata = PolicyBundleMetadata(
        bundle_name=metadata.bundle_name,
        version="2026.03.1",
        loaded_from=metadata.loaded_from,
        lifecycle="draft",
    )

    bundle_id = repo.register_bundle(
        metadata, rules, created_by="alice", creation_reason="initial"
    )
    repo.transition_bundle(
        bundle_id, "candidate", promoted_by="alice", promotion_reason="ready"
    )
    repo.transition_bundle(
        bundle_id,
        "active",
        promoted_by="bob",
        promotion_reason="cab approved",
        validation_artifact="CAB-1",
        evidence_json='{"simulation":"ok"}',
    )

    active = repo.get_active_bundle(metadata.bundle_name)
    assert active is not None
    assert active.id == bundle_id
    assert active.promoted_by == "bob"
    assert active.validation_artifact == "CAB-1"
    history = repo.get_history(metadata.bundle_name)
    assert {item["action"] for item in history} >= {"register", "promote"}


def test_duplicate_registration_rejected(tmp_path) -> None:
    db_path = tmp_path / "registry.db"
    repo = SQLitePolicyBundleRepository(str(db_path))
    repo.initialize()
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    metadata.lifecycle = "draft"
    repo.register_bundle(metadata, rules)
    with pytest.raises(PolicyBundleConflictError, match="same name and version"):
        repo.register_bundle(metadata, rules)


def test_invalid_transition_and_active_validation_artifact_required(tmp_path) -> None:
    db_path = tmp_path / "registry.db"
    repo = SQLitePolicyBundleRepository(str(db_path))
    repo.initialize()
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    metadata.lifecycle = "draft"
    bundle_id = repo.register_bundle(metadata, rules)

    with pytest.raises(
        PolicyBundleInvalidTransitionError, match="invalid lifecycle transition"
    ):
        repo.transition_bundle(
            bundle_id, "active", promoted_by="x", promotion_reason="skip"
        )

    repo.transition_bundle(
        bundle_id, "candidate", promoted_by="x", promotion_reason="ok"
    )
    repo.transition_bundle(
        bundle_id, "approved", promoted_by="x", promotion_reason="peer reviewed"
    )
    with pytest.raises(PolicyBundleInvalidTransitionError, match="validation_artifact"):
        repo.transition_bundle(
            bundle_id, "active", promoted_by="x", promotion_reason="no artifact"
        )
    with pytest.raises(PolicyBundleInvalidTransitionError, match="evidence_json"):
        repo.transition_bundle(
            bundle_id,
            "active",
            promoted_by="x",
            promotion_reason="no evidence",
            validation_artifact="CAB-1",
        )


def test_rollback_to_previous_active(tmp_path) -> None:
    db_path = tmp_path / "registry.db"
    repo = SQLitePolicyBundleRepository(str(db_path))
    repo.initialize()
    rules, meta = load_policy_bundle("src/sena/examples/policies")

    first = PolicyBundleMetadata(
        bundle_name=meta.bundle_name,
        version="1.0.0",
        loaded_from=meta.loaded_from,
        lifecycle="draft",
    )
    second = PolicyBundleMetadata(
        bundle_name=meta.bundle_name,
        version="1.1.0",
        loaded_from=meta.loaded_from,
        lifecycle="draft",
    )

    id1 = repo.register_bundle(first, rules)
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

    id2 = repo.register_bundle(second, rules)
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

    repo.rollback_bundle(
        meta.bundle_name,
        id1,
        promoted_by="ops",
        promotion_reason="incident",
        validation_artifact="INC-1",
    )
    active = repo.get_active_bundle(meta.bundle_name)
    assert active is not None and active.id == id1


def test_migration_tables_exist(tmp_path) -> None:
    db_path = tmp_path / "registry.db"
    repo = SQLitePolicyBundleRepository(str(db_path))
    repo.initialize()
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "bundle_history" in tables
    assert "schema_migrations" in tables


def test_concurrency_registration_unique(tmp_path) -> None:
    db_path = tmp_path / "registry.db"
    repo = SQLitePolicyBundleRepository(str(db_path))
    repo.initialize()
    rules, meta = load_policy_bundle("src/sena/examples/policies")

    errors: list[str] = []

    def worker(version: str) -> None:
        try:
            local_repo = SQLitePolicyBundleRepository(str(db_path))
            local_repo.initialize()
            local_repo.register_bundle(
                PolicyBundleMetadata(
                    bundle_name=meta.bundle_name,
                    version=version,
                    loaded_from=meta.loaded_from,
                    lifecycle="draft",
                ),
                rules,
            )
        except PolicyBundleConflictError as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=worker, args=("same",)) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(errors) == 1


def test_concurrent_promotions_preserve_single_active_invariant(tmp_path) -> None:
    db_path = tmp_path / "registry.db"
    repo = SQLitePolicyBundleRepository(str(db_path))
    repo.initialize()
    rules, meta = load_policy_bundle("src/sena/examples/policies")

    def register_candidate(version: str) -> int:
        bundle_id = repo.register_bundle(
            PolicyBundleMetadata(
                bundle_name=meta.bundle_name,
                version=version,
                loaded_from=meta.loaded_from,
                lifecycle="draft",
            ),
            rules,
        )
        repo.transition_bundle(
            bundle_id, "candidate", promoted_by="ops", promotion_reason="ready"
        )
        return bundle_id

    bundle_a = register_candidate("1.0.0")
    bundle_b = register_candidate("1.1.0")
    errors: list[str] = []

    def promote(bundle_id: int, ticket: str, delay: float) -> None:
        time.sleep(delay)
        try:
            local_repo = SQLitePolicyBundleRepository(str(db_path))
            local_repo.transition_bundle(
                bundle_id,
                "active",
                promoted_by="ops",
                promotion_reason="promote",
                validation_artifact=ticket,
                evidence_json='{"simulation":"ok"}',
            )
        except Exception as exc:  # pragma: no cover - defensive for diagnostics
            errors.append(str(exc))

    t1 = threading.Thread(target=promote, args=(bundle_a, "CAB-1", 0.02))
    t2 = threading.Thread(target=promote, args=(bundle_b, "CAB-2", 0.0))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert errors == []
    with sqlite3.connect(db_path) as conn:
        active_count = conn.execute(
            "SELECT COUNT(*) FROM bundles WHERE name = ? AND lifecycle = 'active'",
            (meta.bundle_name,),
        ).fetchone()[0]
    assert active_count == 1


def test_startup_integrity_check_detects_multiple_active(tmp_path) -> None:
    db_path = tmp_path / "registry.db"
    repo = SQLitePolicyBundleRepository(str(db_path))
    repo.initialize()
    rules, meta = load_policy_bundle("src/sena/examples/policies")
    id1 = repo.register_bundle(
        PolicyBundleMetadata(
            bundle_name=meta.bundle_name,
            version="v1",
            loaded_from=meta.loaded_from,
            lifecycle="draft",
        ),
        rules,
    )
    id2 = repo.register_bundle(
        PolicyBundleMetadata(
            bundle_name=meta.bundle_name,
            version="v2",
            loaded_from=meta.loaded_from,
            lifecycle="draft",
        ),
        rules,
    )

    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP INDEX IF EXISTS idx_bundles_one_active_per_name")
        conn.execute(
            "UPDATE bundles SET lifecycle = 'active' WHERE id IN (?, ?)", (id1, id2)
        )
        conn.commit()

    broken = SQLitePolicyBundleRepository(str(db_path))
    with pytest.raises(
        PolicyStoreIntegrityError, match="multiple active bundles detected"
    ):
        broken.initialize()


def test_lock_contention_raises_domain_conflict_error(tmp_path) -> None:
    db_path = tmp_path / "registry.db"
    repo = SQLitePolicyBundleRepository(str(db_path))
    repo.initialize()

    holder = SQLitePolicyBundleRepository(str(db_path))
    conn = holder._connect()  # test-only lock simulation
    conn.execute("BEGIN IMMEDIATE")
    try:
        contended = SQLitePolicyBundleRepository(
            str(db_path),
            busy_timeout_ms=1,
            lock_retry_attempts=1,
            lock_retry_delay_seconds=0.001,
        )
        with pytest.raises(PolicyBundleConflictError, match="retry budget exhaustion"):
            with contended._write_transaction():
                pass
    finally:
        conn.rollback()
        conn.close()


def test_write_transaction_rolls_back_on_interrupted_write(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "registry.db"
    repo = SQLitePolicyBundleRepository(str(db_path))
    repo.initialize()
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    metadata.lifecycle = "draft"

    original_insert = repo._insert_history

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated interruption")

    monkeypatch.setattr(repo, "_insert_history", _boom)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        repo.register_bundle(metadata, rules)

    with sqlite3.connect(db_path) as conn:
        bundle_rows = conn.execute("SELECT COUNT(*) FROM bundles").fetchone()[0]
        rule_rows = conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0]
    assert bundle_rows == 0
    assert rule_rows == 0

    monkeypatch.setattr(repo, "_insert_history", original_insert)


def test_verify_integrity_reports_sqlite_settings(tmp_path) -> None:
    db_path = tmp_path / "registry.db"
    repo = SQLitePolicyBundleRepository(
        str(db_path), journal_mode="WAL", synchronous="FULL"
    )
    repo.initialize()

    report = repo.verify_integrity()
    assert report["db_integrity_ok"] is True
    assert report["single_active_bundle_ok"] is True
    assert report["journal_mode"] == "WAL"
    assert report["synchronous"] == "FULL"
