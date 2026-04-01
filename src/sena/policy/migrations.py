from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SqlMigration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


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
                    sql=path.read_text(),
                )
            )
        versions = [m.version for m in migrations]
        if len(versions) != len(set(versions)):
            raise ValueError("duplicate migration versions discovered")
        return migrations

    def initialize_table(self, conn) -> None:
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

    def applied_versions(self, conn) -> set[int]:
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
        return {int(row[0]) for row in rows}
