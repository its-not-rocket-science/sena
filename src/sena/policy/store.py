from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from sena.core.enums import RuleDecision, Severity
from sena.core.models import PolicyBundleMetadata, PolicyRule


ALLOWED_TRANSITIONS: set[tuple[str, str]] = {
    ("draft", "candidate"),
    ("candidate", "active"),
    ("active", "deprecated"),
}


@dataclass(frozen=True)
class StoredBundle:
    id: int
    metadata: PolicyBundleMetadata
    rules: list[PolicyRule]
    created_at: str
    release_id: str
    created_by: str
    creation_reason: str | None
    promoted_at: str | None
    promoted_by: str | None
    promotion_reason: str | None
    source_bundle_id: int | None
    integrity_digest: str
    compatibility_notes: str | None
    release_notes: str | None
    migration_notes: str | None
    validation_artifact: str | None
    release_manifest_path: str | None
    signature_verification_strict: bool
    signature_verified: bool
    signature_error: str | None
    signature_key_id: str | None
    signature_verified_at: str | None


class PolicyBundleRepository(Protocol):
    def register_bundle(self, metadata: PolicyBundleMetadata, rules: list[PolicyRule]) -> int: ...

    def get_active_bundle(self, bundle_name: str) -> StoredBundle | None: ...

    def get_bundle(self, bundle_id: int) -> StoredBundle | None: ...


class SQLitePolicyBundleRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 3000")
        return conn

    def initialize(self) -> None:
        migrations_dir = Path(__file__).resolve().parents[3] / "scripts" / "migrations"
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    name TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            applied = {
                row["name"]
                for row in conn.execute("SELECT name FROM schema_migrations").fetchall()
            }
            for migration_path in sorted(migrations_dir.glob("*.sql")):
                if migration_path.name in applied:
                    continue
                conn.executescript(migration_path.read_text())
                conn.execute(
                    "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                    (migration_path.name, datetime.now(timezone.utc).isoformat()),
                )

    def register_bundle(
        self,
        metadata: PolicyBundleMetadata,
        rules: list[PolicyRule],
        *,
        created_by: str = "system",
        creation_reason: str | None = None,
        source_bundle_id: int | None = None,
        compatibility_notes: str | None = None,
        release_notes: str | None = None,
        migration_notes: str | None = None,
        release_manifest_path: str | None = None,
        signature_verification_strict: bool = False,
        signature_verified: bool = False,
        signature_error: str | None = None,
        signature_key_id: str | None = None,
        signature_verified_at: str | None = None,
    ) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        digest = self._bundle_digest(rules)
        release_id = metadata.version
        with self._connect() as conn:
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO bundles (
                        name, version, release_id, lifecycle, created_at, created_by, creation_reason,
                        source_bundle_id, integrity_digest, compatibility_notes, release_notes, migration_notes
                        , release_manifest_path, signature_verification_strict, signature_verified,
                        signature_error, signature_key_id, signature_verified_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        metadata.bundle_name,
                        metadata.version,
                        release_id,
                        metadata.lifecycle,
                        created_at,
                        created_by,
                        creation_reason,
                        source_bundle_id,
                        digest,
                        compatibility_notes,
                        release_notes,
                        migration_notes,
                        release_manifest_path,
                        int(signature_verification_strict),
                        int(signature_verified),
                        signature_error,
                        signature_key_id,
                        signature_verified_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("bundle with same name and version already exists") from exc
            bundle_id = int(cursor.lastrowid)
            conn.executemany(
                """
                INSERT INTO rules (bundle_id, rule_id, hash, content)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        bundle_id,
                        rule.id,
                        self._rule_hash(rule),
                        json.dumps(self._serialize_rule(rule), sort_keys=True, separators=(",", ":")),
                    )
                    for rule in rules
                ],
            )
            self._insert_history(
                conn,
                bundle_id=bundle_id,
                action="register",
                from_lifecycle=None,
                to_lifecycle=metadata.lifecycle,
                actor=created_by,
                reason=creation_reason or "initial registration",
                replaced_bundle_id=None,
                validation_artifact=None,
            )
            return bundle_id

    def transition_bundle(
        self,
        bundle_id: int,
        target_lifecycle: str,
        *,
        promoted_by: str,
        promotion_reason: str,
        validation_artifact: str | None = None,
        action: str = "promote",
    ) -> None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM bundles WHERE id = ?", (bundle_id,)).fetchone()
            if row is None:
                raise ValueError(f"bundle id '{bundle_id}' not found")
            source = row["lifecycle"]
            if (source, target_lifecycle) not in ALLOWED_TRANSITIONS:
                raise ValueError(f"invalid lifecycle transition '{source}' -> '{target_lifecycle}'")
            if target_lifecycle == "active" and not validation_artifact:
                raise ValueError("promotion to active requires validation_artifact")

            replaced_bundle_id: int | None = None
            if target_lifecycle == "active":
                active = conn.execute(
                    "SELECT id FROM bundles WHERE name = ? AND lifecycle = 'active' AND id != ? ORDER BY id DESC LIMIT 1",
                    (row["name"], bundle_id),
                ).fetchone()
                if active is not None:
                    replaced_bundle_id = int(active["id"])
                    conn.execute("UPDATE bundles SET lifecycle = 'deprecated' WHERE id = ?", (replaced_bundle_id,))
                    self._insert_history(
                        conn,
                        bundle_id=replaced_bundle_id,
                        action="auto_deprecate",
                        from_lifecycle="active",
                        to_lifecycle="deprecated",
                        actor=promoted_by,
                        reason=f"Replaced by bundle {bundle_id}",
                        replaced_bundle_id=bundle_id,
                        validation_artifact=validation_artifact,
                    )

            promoted_at = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                UPDATE bundles
                SET lifecycle = ?, promoted_at = ?, promoted_by = ?, promotion_reason = ?, validation_artifact = ?
                WHERE id = ?
                """,
                (target_lifecycle, promoted_at, promoted_by, promotion_reason, validation_artifact, bundle_id),
            )
            self._insert_history(
                conn,
                bundle_id=bundle_id,
                action=action,
                from_lifecycle=source,
                to_lifecycle=target_lifecycle,
                actor=promoted_by,
                reason=promotion_reason,
                replaced_bundle_id=replaced_bundle_id,
                validation_artifact=validation_artifact,
            )


    def set_bundle_lifecycle(self, bundle_id: int, lifecycle: str) -> None:
        bundle = self.get_bundle(bundle_id)
        if bundle is None:
            raise ValueError(f"bundle id '{bundle_id}' not found")
        self.transition_bundle(
            bundle_id,
            lifecycle,
            promoted_by="system",
            promotion_reason="legacy transition",
            validation_artifact="legacy" if lifecycle == "active" else None,
        )

    def rollback_bundle(
        self,
        bundle_name: str,
        to_bundle_id: int,
        *,
        promoted_by: str,
        promotion_reason: str,
        validation_artifact: str,
    ) -> None:
        with self._connect() as conn:
            target = conn.execute(
                "SELECT id, lifecycle, name FROM bundles WHERE id = ? AND name = ?",
                (to_bundle_id, bundle_name),
            ).fetchone()
            if target is None:
                raise ValueError("rollback target bundle not found")
            current = conn.execute(
                "SELECT id FROM bundles WHERE name = ? AND lifecycle = 'active' ORDER BY id DESC LIMIT 1",
                (bundle_name,),
            ).fetchone()
            if current is None:
                raise ValueError("no active bundle to rollback from")
            current_id = int(current["id"])
            if current_id == to_bundle_id:
                raise ValueError("rollback target is already active")

            conn.execute("UPDATE bundles SET lifecycle = 'deprecated' WHERE id = ?", (current_id,))
            self._insert_history(
                conn,
                bundle_id=current_id,
                action="rollback_deprecate",
                from_lifecycle="active",
                to_lifecycle="deprecated",
                actor=promoted_by,
                reason=f"Rolled back to bundle {to_bundle_id}",
                replaced_bundle_id=to_bundle_id,
                validation_artifact=validation_artifact,
            )
            conn.execute(
                """
                UPDATE bundles
                SET lifecycle = 'active', promoted_at = ?, promoted_by = ?, promotion_reason = ?, validation_artifact = ?
                WHERE id = ?
                """,
                (datetime.now(timezone.utc).isoformat(), promoted_by, promotion_reason, validation_artifact, to_bundle_id),
            )
            self._insert_history(
                conn,
                bundle_id=to_bundle_id,
                action="rollback",
                from_lifecycle=target["lifecycle"],
                to_lifecycle="active",
                actor=promoted_by,
                reason=promotion_reason,
                replaced_bundle_id=current_id,
                validation_artifact=validation_artifact,
            )

    def get_bundle(self, bundle_id: int) -> StoredBundle | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM bundles WHERE id = ?", (bundle_id,)).fetchone()
            return self._hydrate_bundle(conn, row)

    def get_bundle_by_version(self, bundle_name: str, version: str) -> StoredBundle | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM bundles WHERE name = ? AND version = ? ORDER BY id DESC LIMIT 1",
                (bundle_name, version),
            ).fetchone()
            return self._hydrate_bundle(conn, row)

    def get_active_bundle(self, bundle_name: str) -> StoredBundle | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM bundles WHERE name = ? AND lifecycle = 'active' ORDER BY id DESC LIMIT 1",
                (bundle_name,),
            ).fetchone()
            return self._hydrate_bundle(conn, row)

    def get_history(self, bundle_name: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT h.* FROM bundle_history h
                JOIN bundles b ON b.id = h.bundle_id
                WHERE b.name = ?
                ORDER BY h.id DESC
                """,
                (bundle_name,),
            ).fetchall()
            return [dict(row) for row in rows]

    def _hydrate_bundle(self, conn: sqlite3.Connection, row: sqlite3.Row | None) -> StoredBundle | None:
        if row is None:
            return None
        rule_rows = conn.execute(
            "SELECT content FROM rules WHERE bundle_id = ? ORDER BY rule_id ASC",
            (int(row["id"]),),
        ).fetchall()
        rules = [self._deserialize_rule(json.loads(r["content"])) for r in rule_rows]
        metadata = PolicyBundleMetadata(
            bundle_name=row["name"],
            version=row["version"],
            loaded_from=f"sqlite://{self.db_path}",
            lifecycle=row["lifecycle"],
            integrity_sha256=row["integrity_digest"],
            policy_file_count=0,
        )
        return StoredBundle(
            id=int(row["id"]),
            metadata=metadata,
            rules=rules,
            created_at=row["created_at"],
            release_id=row["release_id"],
            created_by=row["created_by"],
            creation_reason=row["creation_reason"],
            promoted_at=row["promoted_at"],
            promoted_by=row["promoted_by"],
            promotion_reason=row["promotion_reason"],
            source_bundle_id=row["source_bundle_id"],
            integrity_digest=row["integrity_digest"],
            compatibility_notes=row["compatibility_notes"],
            release_notes=row["release_notes"],
            migration_notes=row["migration_notes"],
            validation_artifact=row["validation_artifact"],
            release_manifest_path=row["release_manifest_path"],
            signature_verification_strict=bool(row["signature_verification_strict"]),
            signature_verified=bool(row["signature_verified"]),
            signature_error=row["signature_error"],
            signature_key_id=row["signature_key_id"],
            signature_verified_at=row["signature_verified_at"],
        )

    def _insert_history(
        self,
        conn: sqlite3.Connection,
        *,
        bundle_id: int,
        action: str,
        from_lifecycle: str | None,
        to_lifecycle: str,
        actor: str,
        reason: str,
        replaced_bundle_id: int | None,
        validation_artifact: str | None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO bundle_history (
                bundle_id, action, from_lifecycle, to_lifecycle, actor, reason,
                replaced_bundle_id, validation_artifact, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bundle_id,
                action,
                from_lifecycle,
                to_lifecycle,
                actor,
                reason,
                replaced_bundle_id,
                validation_artifact,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    @staticmethod
    def _serialize_rule(rule: PolicyRule) -> dict:
        return {
            "id": rule.id,
            "description": rule.description,
            "severity": rule.severity.value,
            "inviolable": rule.inviolable,
            "applies_to": rule.applies_to,
            "condition": rule.condition,
            "decision": rule.decision.value,
            "reason": rule.reason,
        }

    @staticmethod
    def _deserialize_rule(payload: dict) -> PolicyRule:
        return PolicyRule(
            id=payload["id"],
            description=payload["description"],
            severity=Severity(payload["severity"]),
            inviolable=bool(payload["inviolable"]),
            applies_to=list(payload["applies_to"]),
            condition=dict(payload["condition"]),
            decision=RuleDecision(payload["decision"]),
            reason=payload["reason"],
        )

    @classmethod
    def _rule_hash(cls, rule: PolicyRule) -> str:
        canonical = json.dumps(cls._serialize_rule(rule), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def _bundle_digest(cls, rules: list[PolicyRule]) -> str:
        hashes = sorted(cls._rule_hash(rule) for rule in rules)
        canonical = json.dumps(hashes, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
