from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

class MigrationError(Exception):
    """Base class for schema migration failures."""

class MigrationChecksumMismatchError(MigrationError):
    """Raised when an applied migration checksum differs from on-disk migration content."""

class MigrationHistoryError(MigrationError):
    """Raised when migration history is inconsistent with discovered migration files."""

@dataclass(frozen=True)
class SqlMigration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()

@dataclass(frozen=True)
class MigrationRecord:
    version: int
    name: str
    checksum: str
    applied_at: str

@dataclass(frozen=True)
class MigrationRunResult:
    dry_run: bool
    initial_version: int
    target_version: int
    applied_versions: list[int]
    pending_versions: list[int]

class SQLiteMigrationManager:
    def __init__(self, migrations_dir: Path):
        self.migrations_dir = migrations_dir

    def discover(self) -> list[SqlMigration]:
        migrations: list[SqlMigration] = []
        for path in sorted(self.migrations_dir.glob("*.sql")):
            prefix = path.stem.split("_", 1)[0]
            if not prefix.isdigit():
                continue
            migrations.append(
                SqlMigration(
                    version=int(prefix),
                    name=path.name,
                    sql=path.read_text(encoding="utf-8"),
                )
            )
        versions = [m.version for m in migrations]
        if len(versions) != len(set(versions)):
            raise ValueError("duplicate migration versions discovered")
        if migrations:
            expected_versions = list(range(1, migrations[-1].version + 1))
            if versions != expected_versions:
                raise ValueError(
                    f"migration versions must be contiguous and ordered; expected {expected_versions}, got {versions}"
                )
        return migrations

    def initialize_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )

    def applied_versions(self, conn: sqlite3.Connection) -> set[int]:
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
        return {int(row[0]) for row in rows}

    def applied_records(self, conn: sqlite3.Connection) -> dict[int, MigrationRecord]:
        rows = conn.execute(
            "SELECT version, name, checksum, applied_at FROM schema_migrations ORDER BY version ASC"
        ).fetchall()
        return {
            int(row[0]): MigrationRecord(
                version=int(row[0]),
                name=str(row[1]),
                checksum=str(row[2]),
                applied_at=str(row[3]),
            )
            for row in rows
        }

    def inspect_schema(self, conn: sqlite3.Connection) -> dict[str, object]:
        self.initialize_table(conn)
        migrations = self.discover()
        applied = self.applied_records(conn)
        self.validate_applied(conn, migrations=migrations, applied=applied)
        latest_version = migrations[-1].version if migrations else 0
        current_version = max(applied) if applied else 0
        pending_versions = [m.version for m in migrations if m.version not in applied]
        return {
            "current_version": current_version,
            "latest_available_version": latest_version,
            "pending_versions": pending_versions,
            "applied": [
                {
                    "version": record.version,
                    "name": record.name,
                    "checksum": record.checksum,
                    "applied_at": record.applied_at,
                }
                for _, record in sorted(applied.items())
            ],
        }

    def validate_applied(
        self,
        conn: sqlite3.Connection,
        *,
        migrations: list[SqlMigration] | None = None,
        applied: dict[int, MigrationRecord] | None = None,
    ) -> None:
        known = migrations or self.discover()
        applied_records = applied or self.applied_records(conn)
        discovered_by_version = {migration.version: migration for migration in known}

        unknown_applied = sorted(
            version
            for version in applied_records
            if version not in discovered_by_version
        )
        if unknown_applied:
            raise MigrationHistoryError(
                f"database has applied migration versions not present on disk: {unknown_applied}"
            )

        for version, record in sorted(applied_records.items()):
            migration = discovered_by_version[version]
            if record.checksum != migration.checksum:
                raise MigrationChecksumMismatchError(
                    f"checksum mismatch for migration {version} ({migration.name}): "
                    f"db={record.checksum} file={migration.checksum}"
                )

    def upgrade(
        self,
        conn: sqlite3.Connection,
        *,
        dry_run: bool = False,
        target_version: int | None = None,
    ) -> MigrationRunResult:
        self.initialize_table(conn)
        migrations = self.discover()
        applied = self.applied_records(conn)
        self.validate_applied(conn, migrations=migrations, applied=applied)

        if target_version is None:
            resolved_target = migrations[-1].version if migrations else 0
        else:
            resolved_target = target_version
        if resolved_target < 0:
            raise MigrationError("target version must be >= 0")

        available_versions = {migration.version for migration in migrations}
        if resolved_target > 0 and resolved_target not in available_versions:
            raise MigrationError(
                f"target version {resolved_target} not found in available migrations"
            )

        initial_version = max(applied) if applied else 0
        pending = [
            migration
            for migration in migrations
            if migration.version > initial_version
            and migration.version <= resolved_target
        ]

        if dry_run:
            return MigrationRunResult(
                dry_run=True,
                initial_version=initial_version,
                target_version=resolved_target,
                applied_versions=[],
                pending_versions=[migration.version for migration in pending],
            )

        applied_now: list[int] = []
        for migration in pending:
            conn.execute("BEGIN")
            try:
                conn.executescript(migration.sql)
                conn.execute(
                    """
                    INSERT INTO schema_migrations (version, name, checksum, applied_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        migration.version,
                        migration.name,
                        migration.checksum,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()
                applied_now.append(migration.version)

        return MigrationRunResult(
            dry_run=False,
            initial_version=initial_version,
            target_version=resolved_target,
            applied_versions=applied_now,
            pending_versions=[],
        )
