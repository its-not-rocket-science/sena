from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Protocol

from sena.core.enums import RuleDecision, Severity
from sena.core.models import PolicyBundleMetadata, PolicyRule
from sena.policy.migrations import SQLiteMigrationManager
from sena.policy.persistence_models import BundleHistoryRow, BundleRow

ALLOWED_TRANSITIONS: set[tuple[str, str]] = {
    ("draft", "candidate"),
    ("candidate", "active"),
    ("active", "deprecated"),
}


class PolicyStoreError(Exception):
    """Base class for policy store persistence failures."""


class PolicyBundleConflictError(PolicyStoreError):
    """Raised when a write conflicts with uniqueness or concurrent operations."""


class PolicyBundleNotFoundError(PolicyStoreError):
    """Raised when a requested bundle does not exist."""


class PolicyBundleInvalidTransitionError(PolicyStoreError):
    """Raised when lifecycle transition business rules are violated."""


class PolicyStoreIntegrityError(PolicyStoreError):
    """Raised when startup checks or invariants detect a corrupt state."""


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
    def initialize(self) -> None: ...

    def register_bundle(self, metadata: PolicyBundleMetadata, rules: list[PolicyRule], **kwargs: Any) -> int: ...

    def transition_bundle(self, bundle_id: int, target_lifecycle: str, **kwargs: Any) -> None: ...

    def rollback_bundle(
        self,
        bundle_name: str,
        to_bundle_id: int,
        *,
        promoted_by: str,
        promotion_reason: str,
        validation_artifact: str,
    ) -> None: ...

    def get_active_bundle(self, bundle_name: str) -> StoredBundle | None: ...

    def get_bundle(self, bundle_id: int) -> StoredBundle | None: ...

    def get_bundle_by_version(self, bundle_name: str, version: str) -> StoredBundle | None: ...

    def get_history(self, bundle_name: str) -> list[dict[str, Any]]: ...


class SQLitePolicyBundleRepository:
    """SQLite-backed policy repository.

    Concurrency assumptions:
    - lifecycle-changing operations acquire a write lock using ``BEGIN IMMEDIATE``
      so promotion/rollback transitions are serialized across writers.
    - readers remain non-blocking while there is no active writer transaction.
    - lock contention is surfaced as ``PolicyBundleConflictError`` rather than
      leaking sqlite3 implementation exceptions.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._migration_manager = SQLiteMigrationManager(
            Path(__file__).resolve().parents[3] / "scripts" / "migrations"
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 3000")
        return conn

    def initialize(self) -> None:
        with self._connect() as conn:
            self._migration_manager.initialize_table(conn)
            applied_versions = self._migration_manager.applied_versions(conn)
            for migration in self._migration_manager.discover():
                if migration.version in applied_versions:
                    continue
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
            self._run_startup_integrity_checks(conn)

    @contextmanager
    def _write_transaction(self) -> Any:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except sqlite3.OperationalError as exc:
            conn.rollback()
            if "locked" in str(exc).lower():
                raise PolicyBundleConflictError("policy store is busy; retry operation") from exc
            raise
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

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
        with self._write_transaction() as conn:
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO bundles (
                        name, version, release_id, lifecycle, created_at, created_by, creation_reason,
                        source_bundle_id, integrity_digest, compatibility_notes, release_notes, migration_notes,
                        release_manifest_path, signature_verification_strict, signature_verified,
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
                raise PolicyBundleConflictError("bundle with same name and version already exists") from exc
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
                BundleHistoryRow(
                    bundle_id=bundle_id,
                    action="register",
                    from_lifecycle=None,
                    to_lifecycle=metadata.lifecycle,
                    actor=created_by,
                    reason=creation_reason or "initial registration",
                    replaced_bundle_id=None,
                    validation_artifact=None,
                    policy_diff_summary=None,
                    evidence_json=None,
                    break_glass=False,
                    audit_marker=None,
                    created_at=datetime.now(timezone.utc).isoformat(),
                ),
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
        policy_diff_summary: str | None = None,
        evidence_json: str | None = None,
        break_glass: bool = False,
        audit_marker: str | None = None,
        action: str = "promote",
    ) -> None:
        with self._write_transaction() as conn:
            try:
                row = conn.execute("SELECT * FROM bundles WHERE id = ?", (bundle_id,)).fetchone()
                if row is None:
                    raise PolicyBundleNotFoundError(f"bundle id '{bundle_id}' not found")
                source = row["lifecycle"]
                if (source, target_lifecycle) not in ALLOWED_TRANSITIONS:
                    raise PolicyBundleInvalidTransitionError(
                        f"invalid lifecycle transition '{source}' -> '{target_lifecycle}'"
                    )
                if target_lifecycle == "active" and not (validation_artifact or evidence_json or break_glass):
                    raise PolicyBundleInvalidTransitionError(
                        "promotion to active requires validation_artifact or evidence_json unless break_glass is set"
                    )

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
                            BundleHistoryRow(
                                bundle_id=replaced_bundle_id,
                                action="auto_deprecate",
                                from_lifecycle="active",
                                to_lifecycle="deprecated",
                                actor=promoted_by,
                                reason=f"Replaced by bundle {bundle_id}",
                                replaced_bundle_id=bundle_id,
                                validation_artifact=validation_artifact,
                                policy_diff_summary=policy_diff_summary,
                                evidence_json=evidence_json,
                                break_glass=break_glass,
                                audit_marker=audit_marker,
                                created_at=datetime.now(timezone.utc).isoformat(),
                            ),
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
                if target_lifecycle == "active":
                    self._assert_single_active_bundle(conn, row["name"])
                self._insert_history(
                    conn,
                    BundleHistoryRow(
                        bundle_id=bundle_id,
                        action=action,
                        from_lifecycle=source,
                        to_lifecycle=target_lifecycle,
                        actor=promoted_by,
                        reason=promotion_reason,
                        replaced_bundle_id=replaced_bundle_id,
                        validation_artifact=validation_artifact,
                        policy_diff_summary=policy_diff_summary,
                        evidence_json=evidence_json,
                        break_glass=break_glass,
                        audit_marker=audit_marker,
                        created_at=datetime.now(timezone.utc).isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise PolicyBundleConflictError("bundle transition conflicted with repository invariants") from exc

    def set_bundle_lifecycle(self, bundle_id: int, lifecycle: str) -> None:
        bundle = self.get_bundle(bundle_id)
        if bundle is None:
            raise PolicyBundleNotFoundError(f"bundle id '{bundle_id}' not found")
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
        with self._write_transaction() as conn:
            try:
                target = conn.execute(
                    "SELECT id, lifecycle, name FROM bundles WHERE id = ? AND name = ?",
                    (to_bundle_id, bundle_name),
                ).fetchone()
                if target is None:
                    raise PolicyBundleNotFoundError("rollback target bundle not found")
                current = conn.execute(
                    "SELECT id FROM bundles WHERE name = ? AND lifecycle = 'active' ORDER BY id DESC LIMIT 1",
                    (bundle_name,),
                ).fetchone()
                if current is None:
                    raise PolicyBundleInvalidTransitionError("no active bundle to rollback from")
                current_id = int(current["id"])
                if current_id == to_bundle_id:
                    raise PolicyBundleInvalidTransitionError("rollback target is already active")

                conn.execute("UPDATE bundles SET lifecycle = 'deprecated' WHERE id = ?", (current_id,))
                self._insert_history(
                    conn,
                    BundleHistoryRow(
                        bundle_id=current_id,
                        action="rollback_deprecate",
                        from_lifecycle="active",
                        to_lifecycle="deprecated",
                        actor=promoted_by,
                        reason=f"Rolled back to bundle {to_bundle_id}",
                        replaced_bundle_id=to_bundle_id,
                        validation_artifact=validation_artifact,
                        policy_diff_summary=None,
                        evidence_json=None,
                        break_glass=False,
                        audit_marker="rollback_deprecate",
                        created_at=datetime.now(timezone.utc).isoformat(),
                    ),
                )
                conn.execute(
                    """
                    UPDATE bundles
                    SET lifecycle = 'active', promoted_at = ?, promoted_by = ?, promotion_reason = ?, validation_artifact = ?
                    WHERE id = ?
                    """,
                    (
                        datetime.now(timezone.utc).isoformat(),
                        promoted_by,
                        promotion_reason,
                        validation_artifact,
                        to_bundle_id,
                    ),
                )
                self._assert_single_active_bundle(conn, bundle_name)
                self._insert_history(
                    conn,
                    BundleHistoryRow(
                        bundle_id=to_bundle_id,
                        action="rollback",
                        from_lifecycle=target["lifecycle"],
                        to_lifecycle="active",
                        actor=promoted_by,
                        reason=promotion_reason,
                        replaced_bundle_id=current_id,
                        validation_artifact=validation_artifact,
                        policy_diff_summary=None,
                        evidence_json=None,
                        break_glass=False,
                        audit_marker="rollback",
                        created_at=datetime.now(timezone.utc).isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise PolicyBundleConflictError("rollback conflicted with repository invariants") from exc

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
        record = BundleRow(
            id=int(row["id"]),
            name=row["name"],
            version=row["version"],
            release_id=row["release_id"],
            lifecycle=row["lifecycle"],
            created_at=row["created_at"],
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
        rule_rows = conn.execute(
            "SELECT content FROM rules WHERE bundle_id = ? ORDER BY rule_id ASC",
            (record.id,),
        ).fetchall()
        rules = [self._deserialize_rule(json.loads(r["content"])) for r in rule_rows]
        metadata = PolicyBundleMetadata(
            bundle_name=record.name,
            version=record.version,
            loaded_from=f"sqlite://{self.db_path}",
            lifecycle=record.lifecycle,
            integrity_sha256=record.integrity_digest,
            policy_file_count=0,
        )
        return StoredBundle(
            id=record.id,
            metadata=metadata,
            rules=rules,
            created_at=record.created_at,
            release_id=record.release_id,
            created_by=record.created_by,
            creation_reason=record.creation_reason,
            promoted_at=record.promoted_at,
            promoted_by=record.promoted_by,
            promotion_reason=record.promotion_reason,
            source_bundle_id=record.source_bundle_id,
            integrity_digest=record.integrity_digest,
            compatibility_notes=record.compatibility_notes,
            release_notes=record.release_notes,
            migration_notes=record.migration_notes,
            validation_artifact=record.validation_artifact,
            release_manifest_path=record.release_manifest_path,
            signature_verification_strict=record.signature_verification_strict,
            signature_verified=record.signature_verified,
            signature_error=record.signature_error,
            signature_key_id=record.signature_key_id,
            signature_verified_at=record.signature_verified_at,
        )

    def _insert_history(self, conn: sqlite3.Connection, history: BundleHistoryRow) -> None:
        conn.execute(
            """
            INSERT INTO bundle_history (
                bundle_id, action, from_lifecycle, to_lifecycle, actor, reason,
                replaced_bundle_id, validation_artifact, policy_diff_summary, evidence_json,
                break_glass, audit_marker, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                history.bundle_id,
                history.action,
                history.from_lifecycle,
                history.to_lifecycle,
                history.actor,
                history.reason,
                history.replaced_bundle_id,
                history.validation_artifact,
                history.policy_diff_summary,
                history.evidence_json,
                int(history.break_glass),
                history.audit_marker,
                history.created_at,
            ),
        )

    def _run_startup_integrity_checks(self, conn: sqlite3.Connection) -> None:
        check_row = conn.execute("PRAGMA integrity_check").fetchone()
        if check_row is None or check_row[0] != "ok":
            raise PolicyStoreIntegrityError("sqlite integrity check failed")
        bad_rows = conn.execute(
            """
            SELECT name, COUNT(*) AS active_count
            FROM bundles
            WHERE lifecycle = 'active'
            GROUP BY name
            HAVING COUNT(*) > 1
            """
        ).fetchall()
        if bad_rows:
            bundles = ", ".join(f"{row['name']}({row['active_count']})" for row in bad_rows)
            raise PolicyStoreIntegrityError(f"multiple active bundles detected: {bundles}")

    def _assert_single_active_bundle(self, conn: sqlite3.Connection, bundle_name: str) -> None:
        row = conn.execute(
            "SELECT COUNT(*) AS active_count FROM bundles WHERE name = ? AND lifecycle = 'active'",
            (bundle_name,),
        ).fetchone()
        if row is not None and int(row["active_count"]) > 1:
            raise PolicyStoreIntegrityError(f"multiple active bundles detected for '{bundle_name}'")

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


class PostgresPolicyBundleRepository:
    """Architecture placeholder for enterprise relational persistence.

    This class intentionally shares the policy repository contract while
    leaving query implementation for a future psycopg/SQLAlchemy rollout.
    """

    def __init__(self, dsn: str):
        self.dsn = dsn

    def initialize(self) -> None:
        raise NotImplementedError("Postgres adapter not implemented yet; use SQLitePolicyBundleRepository")
