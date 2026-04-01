from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from sena.core.enums import RuleDecision, Severity
from sena.core.models import PolicyBundleMetadata, PolicyRule


@dataclass(frozen=True)
class StoredBundle:
    id: int
    metadata: PolicyBundleMetadata
    rules: list[PolicyRule]
    created_at: str


class PolicyBundleRepository(Protocol):
    def register_bundle(self, metadata: PolicyBundleMetadata, rules: list[PolicyRule]) -> int: ...

    def set_bundle_lifecycle(self, bundle_id: int, lifecycle: str) -> None: ...

    def get_active_bundle(self, bundle_name: str) -> StoredBundle | None: ...

    def get_bundle(self, bundle_id: int) -> StoredBundle | None: ...


class SQLitePolicyBundleRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        migration_path = Path(__file__).resolve().parents[3] / "scripts" / "migrations" / "001_policy_registry.sql"
        with self._connect() as conn:
            conn.executescript(migration_path.read_text())

    def register_bundle(self, metadata: PolicyBundleMetadata, rules: list[PolicyRule]) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO bundles (name, version, lifecycle, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (metadata.bundle_name, metadata.version, metadata.lifecycle, created_at),
            )
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
            return bundle_id

    def set_bundle_lifecycle(self, bundle_id: int, lifecycle: str) -> None:
        if lifecycle not in {"draft", "candidate", "active", "deprecated"}:
            raise ValueError(f"unsupported lifecycle '{lifecycle}'")

        with self._connect() as conn:
            bundle_row = conn.execute("SELECT id, name FROM bundles WHERE id = ?", (bundle_id,)).fetchone()
            if bundle_row is None:
                raise ValueError(f"bundle id '{bundle_id}' not found")

            if lifecycle == "active":
                conn.execute(
                    "UPDATE bundles SET lifecycle = 'deprecated' WHERE name = ? AND lifecycle = 'active' AND id != ?",
                    (bundle_row["name"], bundle_id),
                )

            conn.execute("UPDATE bundles SET lifecycle = ? WHERE id = ?", (lifecycle, bundle_id))

    def get_bundle(self, bundle_id: int) -> StoredBundle | None:
        with self._connect() as conn:
            bundle_row = conn.execute(
                """
                SELECT id, name, version, lifecycle, created_at
                FROM bundles
                WHERE id = ?
                """,
                (bundle_id,),
            ).fetchone()
            if bundle_row is None:
                return None

            rule_rows = conn.execute(
                "SELECT content FROM rules WHERE bundle_id = ? ORDER BY rule_id ASC",
                (bundle_id,),
            ).fetchall()
            rules = [self._deserialize_rule(json.loads(row["content"])) for row in rule_rows]
            metadata = PolicyBundleMetadata(
                bundle_name=bundle_row["name"],
                version=bundle_row["version"],
                loaded_from=f"sqlite://{self.db_path}",
                lifecycle=bundle_row["lifecycle"],
                policy_file_count=0,
            )
            return StoredBundle(
                id=int(bundle_row["id"]),
                metadata=metadata,
                rules=rules,
                created_at=bundle_row["created_at"],
            )

    def get_active_bundle(self, bundle_name: str) -> StoredBundle | None:
        with self._connect() as conn:
            bundle_row = conn.execute(
                """
                SELECT id, name, version, lifecycle, created_at
                FROM bundles
                WHERE name = ? AND lifecycle = 'active'
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT 1
                """,
                (bundle_name,),
            ).fetchone()
            if bundle_row is None:
                return None

            rule_rows = conn.execute(
                "SELECT content FROM rules WHERE bundle_id = ? ORDER BY rule_id ASC",
                (int(bundle_row["id"]),),
            ).fetchall()
            rules = [self._deserialize_rule(json.loads(row["content"])) for row in rule_rows]
            metadata = PolicyBundleMetadata(
                bundle_name=bundle_row["name"],
                version=bundle_row["version"],
                loaded_from=f"sqlite://{self.db_path}",
                lifecycle=bundle_row["lifecycle"],
                policy_file_count=0,
            )
            return StoredBundle(
                id=int(bundle_row["id"]),
                metadata=metadata,
                rules=rules,
                created_at=bundle_row["created_at"],
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
