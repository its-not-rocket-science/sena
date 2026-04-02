from __future__ import annotations

import json

from sena.policy.lifecycle import validate_promotion
from sena.policy.release_signing import (
    generate_release_manifest,
    sign_release_manifest,
    verify_release_manifest,
    write_release_manifest,
)


def test_manifest_sign_and_verify_success(tmp_path) -> None:
    policy_dir = tmp_path / "bundle"
    policy_dir.mkdir()
    (policy_dir / "bundle.yaml").write_text("bundle_name: demo\nversion: 1.2.3\n")
    (policy_dir / "rules.yaml").write_text(
        '[{"id":"r1","description":"d","severity":"low","inviolable":false,'
        '"applies_to":["a"],"condition":{"field":"x","eq":1},"decision":"BLOCK","reason":"ok"}]'
    )

    keyring = tmp_path / "keyring"
    keyring.mkdir()
    (keyring / "ops.key").write_text("shared-secret")

    manifest = generate_release_manifest(policy_dir, key_id="ops", signer_name="Ops")
    signed = sign_release_manifest(manifest, key_path=keyring / "ops.key")
    manifest_path = policy_dir / "release-manifest.json"
    write_release_manifest(signed, manifest_path)

    result = verify_release_manifest(
        policy_dir, manifest_path=manifest_path, keyring_dir=keyring, strict=True
    )
    assert result.valid
    assert result.errors == []


def test_manifest_verify_fails_when_file_is_tampered(tmp_path) -> None:
    policy_dir = tmp_path / "bundle"
    policy_dir.mkdir()
    (policy_dir / "bundle.yaml").write_text("bundle_name: demo\nversion: 1.2.3\n")
    (policy_dir / "rules.yaml").write_text(
        '[{"id":"r1","description":"d","severity":"low","inviolable":false,'
        '"applies_to":["a"],"condition":{"field":"x","eq":1},"decision":"BLOCK","reason":"ok"}]'
    )
    keyring = tmp_path / "keyring"
    keyring.mkdir()
    (keyring / "ops.key").write_text("shared-secret")
    manifest = generate_release_manifest(policy_dir, key_id="ops")
    signed = sign_release_manifest(manifest, key_path=keyring / "ops.key")
    manifest_path = policy_dir / "release-manifest.json"
    write_release_manifest(signed, manifest_path)

    (policy_dir / "rules.yaml").write_text("[]")

    result = verify_release_manifest(
        policy_dir, manifest_path=manifest_path, keyring_dir=keyring, strict=True
    )
    assert not result.valid
    assert any("digest mismatch" in err for err in result.errors)


def test_manifest_verify_fails_when_manifest_is_tampered(tmp_path) -> None:
    policy_dir = tmp_path / "bundle"
    policy_dir.mkdir()
    (policy_dir / "bundle.yaml").write_text("bundle_name: demo\nversion: 1.2.3\n")
    (policy_dir / "rules.yaml").write_text(
        '[{"id":"r1","description":"d","severity":"low","inviolable":false,'
        '"applies_to":["a"],"condition":{"field":"x","eq":1},"decision":"BLOCK","reason":"ok"}]'
    )
    keyring = tmp_path / "keyring"
    keyring.mkdir()
    (keyring / "ops.key").write_text("shared-secret")
    manifest = generate_release_manifest(policy_dir, key_id="ops")
    signed = sign_release_manifest(manifest, key_path=keyring / "ops.key")
    manifest_path = policy_dir / "release-manifest.json"
    write_release_manifest(signed, manifest_path)

    payload = json.loads(manifest_path.read_text())
    payload["aggregate_sha256"] = "bad"
    manifest_path.write_text(json.dumps(payload))

    result = verify_release_manifest(
        policy_dir, manifest_path=manifest_path, keyring_dir=keyring, strict=True
    )
    assert not result.valid
    assert any("aggregate digest mismatch" in err for err in result.errors)


def test_promotion_blocked_when_strict_and_signature_invalid() -> None:
    result = validate_promotion(
        "candidate",
        "active",
        source_rules=[],
        target_rules=[],
        validation_artifact="CAB-1",
        signature_verified=False,
        signature_verification_strict=True,
    )
    assert not result.valid
    assert any("signed release manifest" in err for err in result.errors)


def test_verify_relaxed_mode_allows_missing_signature(tmp_path) -> None:
    policy_dir = tmp_path / "bundle"
    policy_dir.mkdir()
    (policy_dir / "bundle.yaml").write_text("bundle_name: demo\nversion: 1.2.3\n")
    (policy_dir / "rules.yaml").write_text(
        '[{"id":"r1","description":"d","severity":"low","inviolable":false,'
        '"applies_to":["a"],"condition":{"field":"x","eq":1},"decision":"BLOCK","reason":"ok"}]'
    )

    manifest = generate_release_manifest(policy_dir, key_id="unsigned")
    manifest_path = policy_dir / "release-manifest.json"
    write_release_manifest(manifest, manifest_path)

    relaxed = verify_release_manifest(
        policy_dir, manifest_path=manifest_path, keyring_dir=None, strict=False
    )
    strict = verify_release_manifest(
        policy_dir, manifest_path=manifest_path, keyring_dir=None, strict=True
    )

    assert relaxed.valid
    assert not strict.valid
    assert any("unsigned" in err for err in strict.errors)
