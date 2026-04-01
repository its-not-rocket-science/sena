from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BundleRow:
    id: int
    name: str
    version: str
    release_id: str
    lifecycle: str
    created_at: str
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


@dataclass(frozen=True)
class BundleHistoryRow:
    bundle_id: int
    action: str
    from_lifecycle: str | None
    to_lifecycle: str
    actor: str
    reason: str
    replaced_bundle_id: int | None
    validation_artifact: str | None
    policy_diff_summary: str | None
    evidence_json: str | None
    break_glass: bool
    audit_marker: str | None
    created_at: str
