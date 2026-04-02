from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sena.audit.chain import verify_audit_chain
from sena.policy.release_signing import verify_release_manifest


class DisasterRecoveryError(Exception):
    """Raised when backup/restore verification fails."""


@dataclass(frozen=True)
class RestoreVerificationResult:
    valid: bool
    checks: dict[str, Any]
    errors: list[str]


@dataclass(frozen=True)
class BackupArtifacts:
    backup_db_path: Path
    backup_manifest_path: Path
    backup_audit_path: Path | None


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sqlite_integrity_check(db_path: Path) -> dict[str, Any]:
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        return {"ok": False, "result": str(exc)}
    ok = row is not None and row[0] == "ok"
    return {"ok": ok, "result": row[0] if row else None}


def _bundle_digest_from_rule_hashes(rule_hashes: list[str]) -> str:
    canonical = json.dumps(sorted(rule_hashes), separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _rule_hash_from_content(content: str) -> str:
    payload = json.loads(content)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _verify_single_active_bundle_invariant(
    db_path: Path,
) -> tuple[dict[str, Any], list[str]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT name, COUNT(*) AS active_count
            FROM bundles
            WHERE lifecycle = 'active'
            GROUP BY name
            HAVING COUNT(*) > 1
            """
        ).fetchall()
    finally:
        conn.close()

    violations = [
        {"bundle_name": row["name"], "active_count": int(row["active_count"])}
        for row in rows
    ]
    errors = [
        f"bundle '{item['bundle_name']}' has {item['active_count']} active versions"
        for item in violations
    ]
    return {"ok": not violations, "violations": violations}, errors


def _verify_bundle_integrity(
    db_path: Path, *, active_only: bool = True
) -> tuple[dict[str, Any], list[str]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        predicate = "WHERE lifecycle = 'active'" if active_only else ""
        bundles = conn.execute(
            f"SELECT id, name, version, lifecycle, integrity_digest, signature_verification_strict, signature_verified FROM bundles {predicate}"
        ).fetchall()
        checks: list[dict[str, Any]] = []
        errors: list[str] = []
        for bundle in bundles:
            rule_rows = conn.execute(
                "SELECT rule_id, hash, content FROM rules WHERE bundle_id = ? ORDER BY rule_id ASC",
                (bundle["id"],),
            ).fetchall()
            computed_rule_hashes: list[str] = []
            hash_errors: list[str] = []
            for row in rule_rows:
                try:
                    computed = _rule_hash_from_content(row["content"])
                except (json.JSONDecodeError, TypeError) as exc:
                    hash_errors.append(
                        f"invalid rule content for {row['rule_id']}: {exc}"
                    )
                    continue
                computed_rule_hashes.append(computed)
                if computed != row["hash"]:
                    hash_errors.append(f"rule hash mismatch for {row['rule_id']}")

            computed_digest = _bundle_digest_from_rule_hashes(computed_rule_hashes)
            digest_ok = computed_digest == bundle["integrity_digest"]
            rules_present = len(rule_rows) > 0
            signature_required = bool(bundle["signature_verification_strict"])
            signature_ok = (not signature_required) or bool(
                bundle["signature_verified"]
            )

            check = {
                "bundle_id": bundle["id"],
                "bundle_name": bundle["name"],
                "version": bundle["version"],
                "rule_count": len(rule_rows),
                "rules_present": rules_present,
                "digest_ok": digest_ok,
                "stored_integrity_digest": bundle["integrity_digest"],
                "computed_integrity_digest": computed_digest,
                "rule_hash_errors": hash_errors,
                "signature_required": signature_required,
                "signature_ok": signature_ok,
            }
            checks.append(check)

            if not rules_present:
                errors.append(f"bundle {bundle['id']} has no rules")
            if not digest_ok:
                errors.append(f"bundle {bundle['id']} integrity digest mismatch")
            if hash_errors:
                errors.extend(f"bundle {bundle['id']} {e}" for e in hash_errors)
            if not signature_ok:
                errors.append(
                    f"bundle {bundle['id']} requires signature verification but is not verified"
                )

        if active_only and not bundles:
            errors.append("no active bundle found for restore validation")

        return {"bundles_checked": checks}, errors
    finally:
        conn.close()


def create_policy_registry_backup(
    *,
    sqlite_path: Path,
    output_db_path: Path,
    audit_chain_path: Path | None = None,
    output_manifest_path: Path | None = None,
) -> BackupArtifacts:
    output_db_path.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(sqlite_path))
    dst = sqlite3.connect(str(output_db_path))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    backup_audit_path: Path | None = None
    if audit_chain_path is not None and audit_chain_path.exists():
        backup_audit_path = output_db_path.with_suffix(
            output_db_path.suffix + ".audit.jsonl"
        )
        shutil.copy2(audit_chain_path, backup_audit_path)

    manifest_path = output_manifest_path or output_db_path.with_suffix(
        output_db_path.suffix + ".manifest.json"
    )
    integrity = _sqlite_integrity_check(output_db_path)
    manifest = {
        "schema_version": "1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_sqlite_path": str(sqlite_path),
        "backup_db_path": str(output_db_path),
        "backup_db_sha256": _sha256_file(output_db_path),
        "backup_db_integrity": integrity,
        "backup_audit_path": str(backup_audit_path) if backup_audit_path else None,
        "backup_audit_sha256": _sha256_file(backup_audit_path)
        if backup_audit_path
        else None,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return BackupArtifacts(
        backup_db_path=output_db_path,
        backup_manifest_path=manifest_path,
        backup_audit_path=backup_audit_path,
    )


def verify_restored_registry(
    *,
    sqlite_path: Path,
    audit_chain_path: Path | None,
    keyring_dir: Path | None,
    policy_dir: Path | None,
    active_only: bool = True,
) -> RestoreVerificationResult:
    checks: dict[str, Any] = {}
    errors: list[str] = []

    checks["db_integrity"] = _sqlite_integrity_check(sqlite_path)
    if not checks["db_integrity"]["ok"]:
        errors.append("sqlite integrity check failed")

    bundle_checks, bundle_errors = _verify_bundle_integrity(
        sqlite_path, active_only=active_only
    )
    checks["active_bundle_validation"] = bundle_checks
    errors.extend(bundle_errors)

    if audit_chain_path is not None:
        checks["audit_chain"] = verify_audit_chain(str(audit_chain_path))
        if not checks["audit_chain"].get("valid", False):
            errors.append("audit chain verification failed")
    else:
        checks["audit_chain"] = {
            "valid": False,
            "error": "audit chain path not provided",
        }
        errors.append("audit chain path is required for disaster-recovery verification")

    checks["single_active_bundle_invariant"], invariant_errors = (
        _verify_single_active_bundle_invariant(sqlite_path)
    )
    errors.extend(invariant_errors)

    checks["bundle_signature_verification"] = {
        "status": "skipped",
        "reason": "policy_dir or keyring_dir not provided",
    }
    if policy_dir is not None and keyring_dir is not None:
        manifest_path = policy_dir / "release-manifest.json"
        result = verify_release_manifest(
            policy_dir,
            manifest_path=manifest_path,
            keyring_dir=keyring_dir,
            strict=True,
        )
        checks["bundle_signature_verification"] = {
            "status": "ok" if result.valid else "failed",
            "errors": result.errors,
        }
        if not result.valid:
            errors.append("bundle signature verification failed")

    return RestoreVerificationResult(valid=not errors, checks=checks, errors=errors)


def restore_policy_registry_backup(
    *,
    backup_db_path: Path,
    restore_db_path: Path,
    backup_manifest_path: Path | None = None,
    backup_audit_path: Path | None = None,
    restore_audit_path: Path | None = None,
    keyring_dir: Path | None = None,
    policy_dir: Path | None = None,
) -> RestoreVerificationResult:
    if backup_manifest_path and backup_manifest_path.exists():
        manifest = json.loads(backup_manifest_path.read_text())
        expected_sha = manifest.get("backup_db_sha256")
        if expected_sha and expected_sha != _sha256_file(backup_db_path):
            raise DisasterRecoveryError("backup checksum mismatch")

    backup_integrity = _sqlite_integrity_check(backup_db_path)
    if not backup_integrity["ok"]:
        raise DisasterRecoveryError("backup DB failed sqlite integrity_check")

    restore_db_path.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(backup_db_path))
    dst = sqlite3.connect(str(restore_db_path))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    resolved_audit_path = restore_audit_path
    if backup_audit_path and restore_audit_path:
        restore_audit_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_audit_path, restore_audit_path)
        resolved_audit_path = restore_audit_path

    result = verify_restored_registry(
        sqlite_path=restore_db_path,
        audit_chain_path=resolved_audit_path,
        keyring_dir=keyring_dir,
        policy_dir=policy_dir,
    )
    if not result.valid:
        raise DisasterRecoveryError(
            "restore verification failed: " + "; ".join(result.errors)
        )
    return result


def build_backup_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backup policy registry sqlite DB and audit chain"
    )
    parser.add_argument("--sqlite-path", type=Path, required=True)
    parser.add_argument("--output-db", type=Path, required=True)
    parser.add_argument("--audit-chain", type=Path)
    parser.add_argument("--output-manifest", type=Path)
    return parser


def build_restore_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Restore policy registry sqlite DB and verify disaster recovery"
    )
    parser.add_argument("--backup-db", type=Path, required=True)
    parser.add_argument("--restore-db", type=Path, required=True)
    parser.add_argument("--backup-manifest", type=Path)
    parser.add_argument("--backup-audit", type=Path)
    parser.add_argument("--restore-audit", type=Path)
    parser.add_argument("--policy-dir", type=Path)
    parser.add_argument("--keyring-dir", type=Path)
    return parser


def verify_policy_registry_snapshot(
    *,
    sqlite_path: Path,
    audit_chain_path: Path | None = None,
    keyring_dir: Path | None = None,
    policy_dir: Path | None = None,
    active_only: bool = False,
) -> RestoreVerificationResult:
    """Verify a live or restored policy registry snapshot.

    Unlike restore-time validation, this command can run against any registry file
    as an operational health check.
    """

    return verify_restored_registry(
        sqlite_path=sqlite_path,
        audit_chain_path=audit_chain_path,
        keyring_dir=keyring_dir,
        policy_dir=policy_dir,
        active_only=active_only,
    )


def build_verify_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify policy registry sqlite DB integrity and invariants"
    )
    parser.add_argument("--sqlite-path", type=Path, required=True)
    parser.add_argument("--audit-chain", type=Path)
    parser.add_argument("--policy-dir", type=Path)
    parser.add_argument("--keyring-dir", type=Path)
    parser.add_argument(
        "--active-only",
        action="store_true",
        help="Verify only active bundles for digest/rule integrity checks",
    )
    return parser
