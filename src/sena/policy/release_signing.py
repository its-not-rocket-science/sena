from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sena.policy.parser import PolicyParseError, load_policy_bundle


class BundleSignatureError(ValueError):
    pass


class BundleFileDigest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str
    size_bytes: int = Field(ge=0)


class BundleSignerMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key_id: str
    algorithm: str = "hmac-sha256"
    signed_at: str | None = None
    signature: str | None = None
    signer: str | None = None


class BundleReleaseManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1"
    bundle_name: str
    version: str
    created_at: str
    file_digests: list[BundleFileDigest] = Field(min_length=1)
    aggregate_sha256: str
    signer: BundleSignerMetadata
    compatibility_notes: str | None = None
    migration_notes: str | None = None


@dataclass(frozen=True)
class ManifestVerificationResult:
    valid: bool
    errors: list[str]


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _read_key(path: Path) -> bytes:
    try:
        raw = path.read_text().strip()
    except OSError as exc:
        raise BundleSignatureError(f"failed to read key file '{path}': {exc}") from exc
    if not raw:
        raise BundleSignatureError(f"key file '{path}' is empty")
    return raw.encode("utf-8")


def _manifest_signing_payload(manifest: BundleReleaseManifest) -> dict[str, Any]:
    payload = manifest.model_dump()
    payload["signer"]["signature"] = None
    payload["signer"]["signed_at"] = None
    return payload


def _policy_files(policy_dir: Path) -> list[Path]:
    policy_files: list[Path] = []
    for pattern in ("*.yaml", "*.yml", "*.json"):
        for path in sorted(policy_dir.glob(pattern)):
            if path.name in {
                "bundle.yaml",
                "bundle.yml",
                "bundle.json",
                "release-manifest.json",
            }:
                continue
            policy_files.append(path)
    return policy_files


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate_release_manifest(
    policy_dir: Path,
    *,
    bundle_name: str | None = None,
    version: str | None = None,
    key_id: str = "unsigned",
    signer_name: str | None = None,
    created_at: str | None = None,
    compatibility_notes: str | None = None,
    migration_notes: str | None = None,
) -> BundleReleaseManifest:
    rules, metadata = load_policy_bundle(
        policy_dir, bundle_name=bundle_name or "default", version=version or "0"
    )
    if not rules:
        raise BundleSignatureError("policy bundle must include at least one rule")
    files = _policy_files(policy_dir)
    if not files:
        raise BundleSignatureError("no policy files found for release manifest")

    file_digests = [
        BundleFileDigest(
            path=str(path.relative_to(policy_dir)),
            sha256=_file_sha256(path),
            size_bytes=path.stat().st_size,
        )
        for path in files
    ]
    aggregate_input = _canonical_json(
        [item.model_dump() for item in file_digests]
    ).encode("utf-8")
    aggregate_sha256 = hashlib.sha256(aggregate_input).hexdigest()

    return BundleReleaseManifest(
        bundle_name=bundle_name or metadata.bundle_name,
        version=version or metadata.version,
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
        file_digests=file_digests,
        aggregate_sha256=aggregate_sha256,
        signer=BundleSignerMetadata(key_id=key_id, signer=signer_name),
        compatibility_notes=compatibility_notes,
        migration_notes=migration_notes,
    )


def sign_release_manifest(
    manifest: BundleReleaseManifest, *, key_path: Path
) -> BundleReleaseManifest:
    if manifest.signer.algorithm != "hmac-sha256":
        raise BundleSignatureError("only hmac-sha256 is supported")
    key = _read_key(key_path)
    payload = _canonical_json(_manifest_signing_payload(manifest)).encode("utf-8")
    signature = hmac.new(key, payload, hashlib.sha256).hexdigest()
    signed = manifest.model_copy(deep=True)
    signed.signer.signature = signature
    signed.signer.signed_at = datetime.now(timezone.utc).isoformat()
    return signed


def verify_release_manifest(
    policy_dir: Path,
    *,
    manifest_path: Path,
    keyring_dir: Path | None = None,
    strict: bool = False,
) -> ManifestVerificationResult:
    errors: list[str] = []
    try:
        manifest = BundleReleaseManifest.model_validate(
            json.loads(manifest_path.read_text())
        )
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        return ManifestVerificationResult(
            valid=False, errors=[f"invalid release manifest: {exc}"]
        )

    # Bundle identity check against runtime bundle metadata.
    try:
        _, metadata = load_policy_bundle(policy_dir)
    except PolicyParseError as exc:
        return ManifestVerificationResult(
            valid=False, errors=[f"failed to load policy bundle: {exc}"]
        )
    if metadata.bundle_name != manifest.bundle_name:
        errors.append(
            f"bundle_name mismatch: manifest={manifest.bundle_name} bundle={metadata.bundle_name}"
        )
    if metadata.version != manifest.version:
        errors.append(
            f"version mismatch: manifest={manifest.version} bundle={metadata.version}"
        )

    digest_rows: list[dict[str, Any]] = []
    for entry in manifest.file_digests:
        path = policy_dir / entry.path
        if not path.exists():
            errors.append(f"manifest file missing on disk: {entry.path}")
            continue
        actual_sha = _file_sha256(path)
        if actual_sha != entry.sha256:
            errors.append(f"digest mismatch for {entry.path}")
        digest_rows.append(entry.model_dump())

    computed_aggregate = hashlib.sha256(
        _canonical_json(digest_rows).encode("utf-8")
    ).hexdigest()
    if computed_aggregate != manifest.aggregate_sha256:
        errors.append("aggregate digest mismatch")

    if manifest.signer.signature is None:
        if strict:
            errors.append("manifest is unsigned")
    else:
        if keyring_dir is None:
            errors.append("keyring_dir is required for signature verification")
        else:
            key_path = keyring_dir / f"{manifest.signer.key_id}.key"
            if not key_path.exists():
                errors.append(
                    f"trusted key not found for key_id={manifest.signer.key_id}"
                )
            else:
                key = _read_key(key_path)
                payload = _canonical_json(_manifest_signing_payload(manifest)).encode(
                    "utf-8"
                )
                expected = hmac.new(key, payload, hashlib.sha256).hexdigest()
                if not hmac.compare_digest(expected, manifest.signer.signature):
                    errors.append("signature mismatch")

    return ManifestVerificationResult(valid=not errors, errors=errors)


def write_release_manifest(manifest: BundleReleaseManifest, path: Path) -> None:
    path.write_text(json.dumps(manifest.model_dump(), indent=2) + "\n")
