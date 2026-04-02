from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from sena.policy.migrations import (
    MigrationChecksumMismatchError,
    SQLiteMigrationManager,
)
from sena.policy.store import SQLitePolicyBundleRepository


def test_fresh_registry_init_applies_ordered_migrations(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh.db"
    repo = SQLitePolicyBundleRepository(str(db_path))

    before = repo.inspect_schema()
    assert before["current_version"] == 0
    assert before["pending_versions"]

    result = repo.upgrade_schema()
    after = repo.inspect_schema()

    assert result.applied_versions
    assert after["current_version"] == after["latest_available_version"]
    assert after["pending_versions"] == []


def test_upgrade_from_legacy_schema_fixture_is_reproducible(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    legacy_sql = Path(
        "tests/fixtures/migrations/storage_states/legacy_registry_v1.sql"
    ).read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(legacy_sql)

    repo = SQLitePolicyBundleRepository(str(db_path))
    result = repo.upgrade_schema()
    status = repo.inspect_schema()

    assert result.applied_versions == [1, 2, 3, 4, 5]
    assert status["current_version"] == 5


def test_re_running_upgrade_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "idempotent.db"
    repo = SQLitePolicyBundleRepository(str(db_path))

    first = repo.upgrade_schema()
    second = repo.upgrade_schema()

    assert first.applied_versions
    assert second.applied_versions == []


def test_checksum_mismatch_is_detected(tmp_path: Path) -> None:
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    first = migration_dir / "001_create.sql"
    first.write_text("CREATE TABLE t(id INTEGER PRIMARY KEY);", encoding="utf-8")

    manager = SQLiteMigrationManager(migration_dir)
    with sqlite3.connect(tmp_path / "checksum.db") as conn:
        manager.upgrade(conn)

    first.write_text(
        "CREATE TABLE t(id INTEGER PRIMARY KEY, name TEXT);", encoding="utf-8"
    )

    with sqlite3.connect(tmp_path / "checksum.db") as conn:
        with pytest.raises(MigrationChecksumMismatchError, match="checksum mismatch"):
            manager.upgrade(conn)


def test_partial_migration_failure_rolls_back_failed_step_only(tmp_path: Path) -> None:
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    (migration_dir / "001_create.sql").write_text(
        "CREATE TABLE one(id INTEGER PRIMARY KEY);", encoding="utf-8"
    )
    (migration_dir / "002_fail.sql").write_text(
        "CREATE TABL broken(id INTEGER PRIMARY KEY);", encoding="utf-8"
    )
    (migration_dir / "003_never.sql").write_text(
        "CREATE TABLE three(id INTEGER PRIMARY KEY);", encoding="utf-8"
    )

    manager = SQLiteMigrationManager(migration_dir)
    db_path = tmp_path / "partial.db"
    with sqlite3.connect(db_path) as conn:
        with pytest.raises(sqlite3.OperationalError):
            manager.upgrade(conn)

    with sqlite3.connect(db_path) as conn:
        applied = [
            int(row[0])
            for row in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        one_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='one'"
        ).fetchone()
        three_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='three'"
        ).fetchone()

    assert applied == [1]
    assert one_exists is not None
    assert three_exists is None
