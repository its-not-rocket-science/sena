from __future__ import annotations

import json
import sqlite3

import pytest

from sena.audit.chain import append_audit_record
from sena.core.models import PolicyBundleMetadata
from sena.policy.disaster_recovery import (
    DisasterRecoveryError,
    create_policy_registry_backup,
    restore_policy_registry_backup,
)
from sena.policy.parser import load_policy_bundle
from sena.policy.store import SQLitePolicyBundleRepository


def _create_active_registry(db_path, *, version: str = "2026.04.1") -> tuple[str, int]:
    repo = SQLitePolicyBundleRepository(str(db_path))
    repo.initialize()
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    metadata = PolicyBundleMetadata(
        bundle_name=metadata.bundle_name,
        version=version,
        loaded_from=metadata.loaded_from,
        lifecycle="draft",
    )
    bundle_id = repo.register_bundle(metadata, rules, created_by="dr-test")
    repo.transition_bundle(
        bundle_id, "candidate", promoted_by="dr-test", promotion_reason="candidate"
    )
    repo.transition_bundle(
        bundle_id,
        "active",
        promoted_by="dr-test",
        promotion_reason="activate",
        validation_artifact="CAB-DR-1",
    )
    return metadata.bundle_name, bundle_id


def test_restore_valid_backup(tmp_path) -> None:
    source_db = tmp_path / "source.db"
    _create_active_registry(source_db)

    source_audit = tmp_path / "audit.jsonl"
    append_audit_record(str(source_audit), {"event": "bundle.promoted", "bundle_id": 1})

    backup_db = tmp_path / "backup.db"
    artifacts = create_policy_registry_backup(
        sqlite_path=source_db,
        output_db_path=backup_db,
        audit_chain_path=source_audit,
    )

    restored_db = tmp_path / "restored.db"
    restored_audit = tmp_path / "restored-audit.jsonl"
    result = restore_policy_registry_backup(
        backup_db_path=artifacts.backup_db_path,
        restore_db_path=restored_db,
        backup_manifest_path=artifacts.backup_manifest_path,
        backup_audit_path=artifacts.backup_audit_path,
        restore_audit_path=restored_audit,
    )

    assert result.valid is True
    assert result.checks["db_integrity"]["ok"] is True
    assert result.checks["audit_chain"]["valid"] is True
    assert (
        result.checks["active_bundle_validation"]["bundles_checked"][0]["rules_present"]
        is True
    )


def test_restore_corrupt_backup_fails_integrity_check(tmp_path) -> None:
    corrupt_backup = tmp_path / "corrupt.db"
    corrupt_backup.write_bytes(b"not-a-sqlite-db")

    with pytest.raises(DisasterRecoveryError, match="integrity_check"):
        restore_policy_registry_backup(
            backup_db_path=corrupt_backup,
            restore_db_path=tmp_path / "restored.db",
        )


def test_restore_fails_when_active_bundle_missing_rules(tmp_path) -> None:
    source_db = tmp_path / "source.db"
    _, bundle_id = _create_active_registry(source_db)

    source_audit = tmp_path / "audit.jsonl"
    append_audit_record(
        str(source_audit), {"event": "bundle.promoted", "bundle_id": bundle_id}
    )

    backup_db = tmp_path / "backup.db"
    artifacts = create_policy_registry_backup(
        sqlite_path=source_db,
        output_db_path=backup_db,
        audit_chain_path=source_audit,
    )

    with sqlite3.connect(artifacts.backup_db_path) as conn:
        conn.execute("DELETE FROM rules WHERE bundle_id = ?", (bundle_id,))
        conn.commit()

    with pytest.raises(DisasterRecoveryError, match="has no rules"):
        restore_policy_registry_backup(
            backup_db_path=artifacts.backup_db_path,
            restore_db_path=tmp_path / "restored.db",
            backup_audit_path=artifacts.backup_audit_path,
            restore_audit_path=tmp_path / "restored-audit.jsonl",
        )


def test_restore_fails_when_bundle_metadata_mismatches_rule_content(tmp_path) -> None:
    source_db = tmp_path / "source.db"
    _, bundle_id = _create_active_registry(source_db)

    source_audit = tmp_path / "audit.jsonl"
    append_audit_record(
        str(source_audit), {"event": "bundle.promoted", "bundle_id": bundle_id}
    )

    backup_db = tmp_path / "backup.db"
    artifacts = create_policy_registry_backup(
        sqlite_path=source_db,
        output_db_path=backup_db,
        audit_chain_path=source_audit,
    )

    with sqlite3.connect(artifacts.backup_db_path) as conn:
        row = conn.execute(
            "SELECT rule_id, content FROM rules WHERE bundle_id = ? ORDER BY rule_id ASC LIMIT 1",
            (bundle_id,),
        ).fetchone()
        assert row is not None
        payload = json.loads(row[1])
        payload["reason"] = "tampered after backup"
        conn.execute(
            "UPDATE rules SET content = ? WHERE bundle_id = ? AND rule_id = ?",
            (
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                bundle_id,
                row[0],
            ),
        )
        conn.commit()

    with pytest.raises(DisasterRecoveryError, match="digest mismatch"):
        restore_policy_registry_backup(
            backup_db_path=artifacts.backup_db_path,
            restore_db_path=tmp_path / "restored.db",
            backup_audit_path=artifacts.backup_audit_path,
            restore_audit_path=tmp_path / "restored-audit.jsonl",
        )


def test_restore_fails_when_single_active_bundle_invariant_violated(tmp_path) -> None:
    source_db = tmp_path / "source.db"
    bundle_name, _ = _create_active_registry(source_db, version="1.0.0")

    repo = SQLitePolicyBundleRepository(str(source_db))
    rules, meta = load_policy_bundle("src/sena/examples/policies")
    second_bundle = repo.register_bundle(
        PolicyBundleMetadata(
            bundle_name=bundle_name,
            version="1.1.0",
            loaded_from=meta.loaded_from,
            lifecycle="draft",
        ),
        rules,
    )

    source_audit = tmp_path / "audit.jsonl"
    append_audit_record(
        str(source_audit), {"event": "bundle.promoted", "bundle_id": second_bundle}
    )

    backup_db = tmp_path / "backup.db"
    artifacts = create_policy_registry_backup(
        sqlite_path=source_db,
        output_db_path=backup_db,
        audit_chain_path=source_audit,
    )

    with sqlite3.connect(artifacts.backup_db_path) as conn:
        conn.execute("DROP INDEX IF EXISTS idx_bundles_one_active_per_name")
        conn.execute(
            "UPDATE bundles SET lifecycle = 'active' WHERE id = ?", (second_bundle,)
        )
        conn.commit()

    with pytest.raises(DisasterRecoveryError, match="active versions"):
        restore_policy_registry_backup(
            backup_db_path=artifacts.backup_db_path,
            restore_db_path=tmp_path / "restored.db",
            backup_audit_path=artifacts.backup_audit_path,
            restore_audit_path=tmp_path / "restored-audit.jsonl",
        )
