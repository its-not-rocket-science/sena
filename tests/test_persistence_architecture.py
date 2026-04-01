from __future__ import annotations
from pathlib import Path

import sqlite3

import pytest

from sena.core.models import PolicyBundleMetadata
from sena.policy.migrations import SQLiteMigrationManager
from sena.policy.parser import load_policy_bundle
from sena.policy.store import PostgresPolicyBundleRepository, SQLitePolicyBundleRepository


def _sqlite_repo(tmp_path):
    db_path = tmp_path / "registry.db"
    repo = SQLitePolicyBundleRepository(str(db_path))
    repo.initialize()
    return repo, db_path


def test_sqlite_migrations_are_explicit_and_versioned(tmp_path) -> None:
    repo, db_path = _sqlite_repo(tmp_path)
    _ = repo
    manager = SQLiteMigrationManager(Path("scripts/migrations"))
    migrations = manager.discover()
    assert [m.version for m in migrations] == sorted(m.version for m in migrations)
    assert all(m.checksum for m in migrations)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT version, checksum FROM schema_migrations ORDER BY version").fetchall()
    assert [r[0] for r in rows] == [m.version for m in migrations]
    assert [r[1] for r in rows] == [m.checksum for m in migrations]


def test_sqlite_migration_initialize_is_idempotent(tmp_path) -> None:
    repo, db_path = _sqlite_repo(tmp_path)
    repo.initialize()
    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    assert count == 5


def test_repository_contract_register_promote_and_history(tmp_path) -> None:
    repo, _ = _sqlite_repo(tmp_path)
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    metadata = PolicyBundleMetadata(
        bundle_name=metadata.bundle_name,
        version="2026.04.1",
        loaded_from=metadata.loaded_from,
        lifecycle="draft",
    )

    bundle_id = repo.register_bundle(
        metadata,
        rules,
        created_by="contract-user",
        release_notes="Contract test release",
        migration_notes="No-op",
        compatibility_notes="Compatible",
        release_manifest_path="release-manifest.json",
        signature_verification_strict=True,
        signature_verified=True,
        signature_key_id="ops",
        signature_verified_at="2026-04-01T00:00:00+00:00",
    )
    repo.transition_bundle(bundle_id, "candidate", promoted_by="contract-user", promotion_reason="ready")
    repo.transition_bundle(
        bundle_id,
        "active",
        promoted_by="contract-user",
        promotion_reason="approved",
        validation_artifact="CAB-42",
    )

    active = repo.get_active_bundle(metadata.bundle_name)
    assert active is not None
    assert active.id == bundle_id
    assert active.release_manifest_path == "release-manifest.json"
    assert active.signature_verified is True
    assert active.migration_notes == "No-op"

    history = repo.get_history(metadata.bundle_name)
    assert len(history) >= 3
    assert history[0]["to_lifecycle"] in {"active", "deprecated"}


def test_postgres_adapter_is_explicit_about_unimplemented_backend() -> None:
    repo = PostgresPolicyBundleRepository("postgresql://localhost/sena")
    with pytest.raises(NotImplementedError, match="not implemented"):
        repo.initialize()
