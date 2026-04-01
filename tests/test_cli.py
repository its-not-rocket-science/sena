import json
import os
import subprocess
import sys


def _run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "sena.cli.main", *args]
    env = dict(os.environ)
    env["PYTHONPATH"] = f"src:{env.get('PYTHONPATH', '')}".rstrip(":")
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def test_cli_json_output_contains_audit_fields() -> None:
    result = _run_cli([
        "src/sena/examples/scenarios/demo_vendor_payment_block_unverified.json",
        "--json",
    ])
    result.check_returncode()
    payload = json.loads(result.stdout)

    assert payload["decision_id"].startswith("dec_")
    assert payload["decision"] == payload["outcome"]
    assert payload["policy_bundle"]["bundle_name"] == "enterprise-compliance-controls"
    assert "precedence_explanation" in payload["reasoning"]
    assert "decision_timestamp" in payload
    assert "decision_hash" in payload




def test_cli_review_package_output() -> None:
    result = _run_cli([
        "src/sena/examples/scenarios/demo_vendor_payment_block_unverified.json",
        "--review-package",
    ])
    result.check_returncode()
    payload = json.loads(result.stdout)

    assert payload["package_type"] == "sena.decision_review_package"
    assert payload["decision_summary"]["outcome"] == "BLOCKED"
    assert "matched" in payload["rules"]
    assert "normalized_source_system_references" in payload

def test_policy_init_validate_and_test_commands(tmp_path) -> None:
    bundle_dir = tmp_path / "bundle"

    init_result = _run_cli(["policy", "init", str(bundle_dir)])
    init_result.check_returncode()
    assert (bundle_dir / "bundle.yaml").exists()
    assert (bundle_dir / "payments.yaml").exists()
    assert (bundle_dir / "tests" / "policy_tests.json").exists()

    validate_result = _run_cli(["policy", "validate", "--policy-dir", str(bundle_dir)])
    validate_result.check_returncode()
    validate_payload = json.loads(validate_result.stdout)
    assert validate_payload["status"] == "ok"
    assert validate_payload["rule_count"] >= 1

    test_result = _run_cli(
        [
            "policy",
            "test",
            "--policy-dir",
            str(bundle_dir),
            "--test-file",
            str(bundle_dir / "tests" / "policy_tests.json"),
        ]
    )
    test_result.check_returncode()
    test_payload = json.loads(test_result.stdout)
    assert test_payload["failures"] == 0


def test_policy_validate_returns_human_readable_error(tmp_path) -> None:
    bundle_dir = tmp_path / "broken"
    bundle_dir.mkdir()
    (bundle_dir / "invalid.yaml").write_text("this is not a list")

    result = _run_cli(["policy", "validate", "--policy-dir", str(bundle_dir)])
    assert result.returncode != 0
    assert "Policy validation failed:" in result.stderr or "Policy validation failed:" in result.stdout

def test_registry_lifecycle_commands(tmp_path) -> None:
    db_path = tmp_path / "registry.db"
    base = ["registry", "--sqlite-path", str(db_path)]

    register = _run_cli(
        base
        + [
            "register",
            "--policy-dir",
            "src/sena/examples/policies",
            "--bundle-name",
            "enterprise-compliance-controls",
            "--bundle-version",
            "2026.05",
            "--created-by",
            "ops",
        ]
    )
    register.check_returncode()
    bundle_id = json.loads(register.stdout)["bundle_id"]

    validate = _run_cli(base + ["validate-promotion", "--bundle-id", str(bundle_id), "--target-lifecycle", "candidate"])
    validate.check_returncode()

    to_candidate = _run_cli(
        base
        + [
            "promote",
            "--bundle-id",
            str(bundle_id),
            "--target-lifecycle",
            "candidate",
            "--promoted-by",
            "ops",
            "--promotion-reason",
            "ready",
        ]
    )
    to_candidate.check_returncode()

    to_active = _run_cli(
        base
        + [
            "promote",
            "--bundle-id",
            str(bundle_id),
            "--target-lifecycle",
            "active",
            "--promoted-by",
            "ops",
            "--promotion-reason",
            "go",
            "--validation-artifact",
            "CAB-123",
        ]
    )
    to_active.check_returncode()

    history = _run_cli(base + ["inspect-history", "--bundle-name", "enterprise-compliance-controls"])
    history.check_returncode()
    assert json.loads(history.stdout)["history"]


def test_bundle_release_manifest_commands(tmp_path) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "bundle.yaml").write_text("bundle_name: demo\nversion: 1.0.0\n")
    (bundle_dir / "rules.yaml").write_text(
        '[{"id":"r1","description":"d","severity":"low","inviolable":false,"applies_to":["a"],"condition":{"field":"x","eq":1},"decision":"BLOCK","reason":"ok"}]'
    )
    keyring = tmp_path / "keyring"
    keyring.mkdir()
    (keyring / "ops.key").write_text("shared-secret")
    manifest_path = bundle_dir / "release-manifest.json"

    generate = _run_cli(
        [
            "bundle-release",
            "generate-manifest",
            "--policy-dir",
            str(bundle_dir),
            "--output",
            str(manifest_path),
            "--key-id",
            "ops",
        ]
    )
    generate.check_returncode()

    sign = _run_cli(
        [
            "bundle-release",
            "sign-manifest",
            "--manifest-path",
            str(manifest_path),
            "--key-file",
            str(keyring / "ops.key"),
        ]
    )
    sign.check_returncode()

    verify = _run_cli(
        [
            "bundle-release",
            "verify-manifest",
            "--policy-dir",
            str(bundle_dir),
            "--manifest-path",
            str(manifest_path),
            "--keyring-dir",
            str(keyring),
            "--strict",
        ]
    )
    verify.check_returncode()


def test_policy_schema_migration_commands(tmp_path) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "bundle.yaml").write_text(
        "bundle_name: demo\nversion: 1.0.0\nschema_version: '1'\n"
    )
    (bundle_dir / "rules.yaml").write_text(
        """
- id: r1
  description: d
  severity: low
  inviolable: false
  action: approve_vendor_payment
  condition:
    field: amount
    gt: 5
  decision: ALLOW
  reason: ok
""".strip()
        + "\n"
    )

    inspect = _run_cli(["policy", "schema-version", "--policy-dir", str(bundle_dir)])
    inspect.check_returncode()
    inspect_payload = json.loads(inspect.stdout)
    assert inspect_payload["schema_version"] == "1"

    dry_run = _run_cli(["policy", "migrate", "--policy-dir", str(bundle_dir), "--dry-run"])
    dry_run.check_returncode()
    dry_payload = json.loads(dry_run.stdout)
    assert dry_payload["changed_files"] == ["bundle.yaml", "rules.yaml"]

    apply = _run_cli(["policy", "migrate", "--policy-dir", str(bundle_dir)])
    apply.check_returncode()

    compat = _run_cli(["policy", "verify-compatibility", "--policy-dir", str(bundle_dir)])
    compat.check_returncode()
    compat_payload = json.loads(compat.stdout)
    assert compat_payload["compatible"] is True


def test_policy_verify_compatibility_fails_for_incompatible_runtime(tmp_path) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "bundle.yaml").write_text(
        """
bundle_name: demo
version: 1.0.0
schema_version: '2'
runtime_compatibility:
  min_evaluator_version: '9.0.0'
  max_evaluator_version: '10.0.0'
""".strip()
        + "\n"
    )
    (bundle_dir / "rules.yaml").write_text(
        '[{"id":"r1","description":"d","severity":"low","inviolable":false,"applies_to":["a"],"condition":{"field":"x","eq":1},"decision":"ALLOW","reason":"ok"}]'
    )

    result = _run_cli(["policy", "verify-compatibility", "--policy-dir", str(bundle_dir)])
    assert result.returncode != 0
    assert "compatibility check failed" in (result.stderr + result.stdout).lower()
