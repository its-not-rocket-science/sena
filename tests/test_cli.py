import json
import os
import subprocess
import sys
from pathlib import Path


def _run_cli(
    args: list[str], extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "sena.cli.main", *args]
    env = dict(os.environ)
    env["PYTHONPATH"] = f"src:{env.get('PYTHONPATH', '')}".rstrip(":")
    if extra_env:
        env.update(extra_env)
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def test_cli_json_output_contains_audit_fields() -> None:
    result = _run_cli(
        [
            "src/sena/examples/scenarios/demo_vendor_payment_block_unverified.json",
            "--json",
        ]
    )
    result.check_returncode()
    payload = json.loads(result.stdout)

    assert payload["decision_id"].startswith("dec_")
    assert payload["decision"] == payload["outcome"]
    assert payload["policy_bundle"]["bundle_name"] == "enterprise-compliance-controls"
    assert "precedence_explanation" in payload["reasoning"]
    assert "decision_timestamp" in payload
    assert "decision_hash" in payload


def test_cli_review_package_output() -> None:
    result = _run_cli(
        [
            "src/sena/examples/scenarios/demo_vendor_payment_block_unverified.json",
            "--review-package",
        ]
    )
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


def test_policy_test_manifest_yaml_format(tmp_path) -> None:
    bundle_dir = tmp_path / "bundle"
    _run_cli(["policy", "init", str(bundle_dir)]).check_returncode()
    tests_yaml = tmp_path / "tests.yaml"
    tests_yaml.write_text(
        """
tests:
  - name: Block unverified vendor payment
    input:
      action: approve_vendor_payment
      vendor_verified: false
      amount: 10000
    expected: BLOCKED
""".strip()
    )
    result = _run_cli(
        [
            "policy",
            "test",
            "--bundle",
            str(bundle_dir),
            "--tests",
            str(tests_yaml),
        ]
    )
    result.check_returncode()
    payload = json.loads(result.stdout)
    assert payload["failures"] == 0


def test_policy_validate_returns_human_readable_error(tmp_path) -> None:
    bundle_dir = tmp_path / "broken"
    bundle_dir.mkdir()
    (bundle_dir / "invalid.yaml").write_text("this is not a list")

    result = _run_cli(["policy", "validate", "--policy-dir", str(bundle_dir)])
    assert result.returncode != 0
    assert (
        "Policy validation failed:" in result.stderr
        or "Policy validation failed:" in result.stdout
    )


def test_registry_lifecycle_commands(tmp_path) -> None:
    db_path = tmp_path / "registry.db"
    base = ["registry", "--sqlite-path", str(db_path)]
    scenarios_path = tmp_path / "scenarios.json"
    scenarios_path.write_text(
        json.dumps(
            {
                "s1": {
                    "action_type": "approve_vendor_payment",
                    "attributes": {"amount": 10, "vendor_verified": True},
                    "facts": {},
                }
            }
        )
    )

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

    validate = _run_cli(
        base
        + [
            "validate-promotion",
            "--bundle-id",
            str(bundle_id),
            "--target-lifecycle",
            "candidate",
        ]
    )
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
            "--simulation-scenarios",
            str(scenarios_path),
        ]
    )
    to_active.check_returncode()

    history = _run_cli(
        base + ["inspect-history", "--bundle-name", "enterprise-compliance-controls"]
    )
    history.check_returncode()
    assert json.loads(history.stdout)["history"]


def test_bundle_rollback_by_version_command(tmp_path) -> None:
    db_path = tmp_path / "registry.db"
    base = ["registry", "--sqlite-path", str(db_path)]
    bundle_v1 = tmp_path / "bundle_v1"
    bundle_v2 = tmp_path / "bundle_v2"
    bundle_v1.mkdir()
    bundle_v2.mkdir()
    for filename in ["bundle.yaml", "payments.yaml", "refunds.yaml", "account_access.yaml", "data_access.yaml"]:
        source = Path("src/sena/examples/policies") / filename
        bundle_v1.joinpath(filename).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        bundle_v2.joinpath(filename).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    bundle_v1.joinpath("bundle.yaml").write_text(
        bundle_v1.joinpath("bundle.yaml").read_text(encoding="utf-8").replace('version: 2026.03', 'version: "2026.10"'),
        encoding="utf-8",
    )
    bundle_v2.joinpath("bundle.yaml").write_text(
        bundle_v2.joinpath("bundle.yaml").read_text(encoding="utf-8").replace('version: 2026.03', 'version: "2026.11"'),
        encoding="utf-8",
    )
    r1 = _run_cli(
        base
        + [
            "register",
            "--policy-dir",
            str(bundle_v1),
            "--bundle-name",
            "enterprise-compliance-controls",
            "--bundle-version",
            "2026.10",
        ]
    )
    r1.check_returncode()
    id1 = json.loads(r1.stdout)["bundle_id"]
    _run_cli(
        base
        + [
            "promote",
            "--bundle-id",
            str(id1),
            "--target-lifecycle",
            "candidate",
            "--promoted-by",
            "ops",
            "--promotion-reason",
            "ready",
        ]
    ).check_returncode()
    _run_cli(
        base
        + [
            "promote",
            "--bundle-id",
            str(id1),
            "--target-lifecycle",
            "active",
            "--promoted-by",
            "ops",
            "--promotion-reason",
            "go",
            "--validation-artifact",
            "CAB-1",
            "--simulation-scenarios",
            "examples/simulation_scenarios.json",
        ]
    ).check_returncode()
    r2 = _run_cli(
        base
        + [
            "register",
            "--policy-dir",
            str(bundle_v2),
            "--bundle-name",
            "enterprise-compliance-controls",
            "--bundle-version",
            "2026.11",
        ]
    )
    r2.check_returncode()
    id2 = json.loads(r2.stdout)["bundle_id"]
    _run_cli(
        base
        + [
            "promote",
            "--bundle-id",
            str(id2),
            "--target-lifecycle",
            "candidate",
            "--promoted-by",
            "ops",
            "--promotion-reason",
            "ready",
        ]
    ).check_returncode()
    _run_cli(
        base
        + [
            "promote",
            "--bundle-id",
            str(id2),
            "--target-lifecycle",
            "active",
            "--promoted-by",
            "ops",
            "--promotion-reason",
            "go",
            "--validation-artifact",
            "CAB-2",
            "--simulation-scenarios",
            "examples/simulation_scenarios.json",
        ]
    ).check_returncode()

    rollback = _run_cli(
        [
            "bundle",
            "rollback",
            "--sqlite-path",
            str(db_path),
            "--bundle-name",
            "enterprise-compliance-controls",
            "--version",
            "2026.10",
        ]
    )
    rollback.check_returncode()
    assert json.loads(rollback.stdout)["active_bundle_id"] == id1


def test_registry_promote_break_glass_without_artifact(tmp_path) -> None:
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
            "2026.06",
        ]
    )
    register.check_returncode()
    bundle_id = json.loads(register.stdout)["bundle_id"]
    _run_cli(
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
    ).check_returncode()
    promote = _run_cli(
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
            "incident",
            "--break-glass",
            "--break-glass-reason",
            "sev1",
        ]
    )
    promote.check_returncode()


def test_registry_promote_fails_when_simulation_missing(tmp_path) -> None:
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
            "2026.07",
        ]
    )
    register.check_returncode()
    bundle_id = json.loads(register.stdout)["bundle_id"]
    _run_cli(
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
    ).check_returncode()
    missing_sim = _run_cli(
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
            "CAB-1",
        ]
    )
    assert missing_sim.returncode != 0
    assert "missing_simulation_report" in (missing_sim.stderr + missing_sim.stdout)


def test_registry_promote_idempotent_repeated_attempt(tmp_path) -> None:
    db_path = tmp_path / "registry.db"
    base = ["registry", "--sqlite-path", str(db_path)]
    scenarios_path = tmp_path / "scenarios.json"
    scenarios_path.write_text(
        json.dumps(
            {
                "s1": {
                    "action_type": "approve_vendor_payment",
                    "attributes": {"amount": 10, "vendor_verified": True},
                    "facts": {},
                }
            }
        )
    )
    register = _run_cli(
        base
        + [
            "register",
            "--policy-dir",
            "src/sena/examples/policies",
            "--bundle-name",
            "enterprise-compliance-controls",
            "--bundle-version",
            "2026.08",
        ]
    )
    register.check_returncode()
    bundle_id = json.loads(register.stdout)["bundle_id"]
    _run_cli(
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
    ).check_returncode()
    _run_cli(
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
            "CAB-1",
            "--simulation-scenarios",
            str(scenarios_path),
        ]
    ).check_returncode()
    second = _run_cli(
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
            "go-again",
        ]
    )
    second.check_returncode()
    assert json.loads(second.stdout)["idempotent"] is True


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


def test_audit_commands_verify_summarize_locate(tmp_path) -> None:
    from sena.audit.chain import append_audit_record
    from sena.audit.sinks import JsonlFileAuditSink, RotationPolicy

    sink = JsonlFileAuditSink(
        path=str(tmp_path / "audit.jsonl"), rotation=RotationPolicy(max_file_bytes=280)
    )
    append_audit_record(sink, {"decision_id": "dec-1", "outcome": "APPROVED"})
    append_audit_record(sink, {"decision_id": "dec-2", "outcome": "BLOCKED"})
    append_audit_record(sink, {"decision_id": "dec-3", "outcome": "ESCALATE"})

    verify = _run_cli(
        ["audit", "--audit-path", str(tmp_path / "audit.jsonl"), "verify"]
    )
    verify.check_returncode()
    verify_payload = json.loads(verify.stdout)
    assert verify_payload["valid"] is True

    summarize = _run_cli(
        ["audit", "--audit-path", str(tmp_path / "audit.jsonl"), "summarize"]
    )
    summarize.check_returncode()
    summary_payload = json.loads(summarize.stdout)
    assert summary_payload["segment_count"] >= 1
    assert summary_payload["last_decision_id"] == "dec-3"

    locate = _run_cli(
        [
            "audit",
            "--audit-path",
            str(tmp_path / "audit.jsonl"),
            "locate-decision",
            "dec-2",
        ]
    )
    locate.check_returncode()
    locate_payload = json.loads(locate.stdout)
    assert locate_payload["found"] is True
    assert locate_payload["decision_id"] == "dec-2"


def test_replay_drift_command(tmp_path) -> None:
    replay_path = tmp_path / "replay.json"
    replay_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "c1",
                        "proposal": {
                            "action_type": "approve_vendor_payment",
                            "request_id": "req-1",
                            "actor_id": "user-1",
                            "actor_role": "finance_analyst",
                            "attributes": {
                                "amount": 500,
                                "vendor_verified": True,
                                "source_system": "jira",
                            },
                            "action_origin": "human",
                        },
                        "facts": {},
                    }
                ]
            }
        )
    )
    result = _run_cli(
        [
            "replay",
            "drift",
            "--replay-file",
            str(replay_path),
            "--baseline-policy-dir",
            "src/sena/examples/policies",
            "--candidate-policy-dir",
            "src/sena/examples/policies",
        ]
    )
    result.check_returncode()
    payload = json.loads(result.stdout)
    assert payload["replay_type"] == "sena.ai_workflow_drift"
    assert payload["changed_outcomes"] == 0


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

    dry_run = _run_cli(
        ["policy", "migrate", "--policy-dir", str(bundle_dir), "--dry-run"]
    )
    dry_run.check_returncode()
    dry_payload = json.loads(dry_run.stdout)
    assert dry_payload["changed_files"] == ["bundle.yaml", "rules.yaml"]

    apply = _run_cli(["policy", "migrate", "--policy-dir", str(bundle_dir)])
    apply.check_returncode()

    compat = _run_cli(
        ["policy", "verify-compatibility", "--policy-dir", str(bundle_dir)]
    )
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

    result = _run_cli(
        ["policy", "verify-compatibility", "--policy-dir", str(bundle_dir)]
    )
    assert result.returncode != 0
    assert "compatibility check failed" in (result.stderr + result.stdout).lower()


def test_production_check_passes_for_default_dev_configuration() -> None:
    result = _run_cli(["production-check", "--format", "json"])
    result.check_returncode()
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["fatal_failure_count"] == 0


def test_production_check_fails_for_invalid_timeout_configuration() -> None:
    result = _run_cli(
        ["production-check", "--format", "json"],
        extra_env={"SENA_REQUEST_TIMEOUT_SECONDS": "0"},
    )
    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "request limits and timeout sanity" in payload["fatal_failures"]


def test_registry_backup_restore_and_verify_commands(tmp_path) -> None:
    from sena.audit.chain import append_audit_record

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
            "2026.09",
        ]
    )
    register.check_returncode()
    bundle_id = json.loads(register.stdout)["bundle_id"]
    _run_cli(
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
    ).check_returncode()
    _run_cli(
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
            "CAB-verify",
            "--break-glass",
            "--break-glass-reason",
            "drill",
        ]
    ).check_returncode()

    audit_path = tmp_path / "audit.jsonl"
    append_audit_record(str(audit_path), {"event": "drill", "bundle_id": bundle_id})
    backup_db = tmp_path / "backup.db"
    backup = _run_cli(
        base
        + ["backup", "--output-db", str(backup_db), "--audit-chain", str(audit_path)]
    )
    backup.check_returncode()
    backup_payload = json.loads(backup.stdout)

    restored_db = tmp_path / "restored.db"
    restored_audit = tmp_path / "restored.audit.jsonl"
    restore = _run_cli(
        base
        + [
            "restore",
            "--backup-db",
            backup_payload["backup_db_path"],
            "--backup-manifest",
            backup_payload["backup_manifest_path"],
            "--backup-audit",
            backup_payload["backup_audit_path"],
            "--restore-db",
            str(restored_db),
            "--restore-audit",
            str(restored_audit),
        ]
    )
    restore.check_returncode()

    verify = _run_cli(
        [
            "registry",
            "--sqlite-path",
            str(restored_db),
            "verify",
            "--audit-chain",
            str(restored_audit),
        ]
    )
    verify.check_returncode()
    verify_payload = json.loads(verify.stdout)
    assert verify_payload["status"] == "ok"
    assert verify_payload["checks"]["db_integrity"]["ok"] is True


def test_audit_archive_verify_restore_workflow(tmp_path) -> None:
    from sena.audit.chain import append_audit_record
    from sena.audit.sinks import JsonlFileAuditSink, RotationPolicy

    sink = JsonlFileAuditSink(
        path=str(tmp_path / "audit.jsonl"), rotation=RotationPolicy(max_file_bytes=250)
    )
    for i in range(5):
        append_audit_record(sink, {"decision_id": f"dec-{i}", "outcome": "APPROVED"})

    archive = _run_cli(
        [
            "audit",
            "--audit-path",
            str(tmp_path / "audit.jsonl"),
            "archive",
            "--archive-dir",
            str(tmp_path / "archive"),
        ]
    )
    archive.check_returncode()
    archive_payload = json.loads(archive.stdout)
    assert archive_payload["segments"] >= 2

    verify_archive = _run_cli(
        [
            "audit",
            "--audit-path",
            str(tmp_path / "audit.jsonl"),
            "verify-archive",
            "--archive-manifest",
            archive_payload["manifest_path"],
        ]
    )
    verify_archive.check_returncode()
    assert json.loads(verify_archive.stdout)["valid"] is True

    restore = _run_cli(
        [
            "audit",
            "--audit-path",
            str(tmp_path / "audit.jsonl"),
            "restore-archive",
            "--archive-manifest",
            archive_payload["manifest_path"],
            "--restore-audit-path",
            str(tmp_path / "restore" / "audit.jsonl"),
            "--verify-after-restore",
        ]
    )
    restore.check_returncode()
    assert json.loads(restore.stdout)["verify"]["valid"] is True


def test_audit_verify_archive_reports_missing_segment(tmp_path) -> None:
    from sena.audit.archive import create_audit_archive
    from sena.audit.chain import append_audit_record
    from sena.audit.sinks import JsonlFileAuditSink, RotationPolicy

    sink = JsonlFileAuditSink(
        path=str(tmp_path / "audit.jsonl"), rotation=RotationPolicy(max_file_bytes=250)
    )
    for i in range(4):
        append_audit_record(sink, {"decision_id": f"dec-{i}", "outcome": "APPROVED"})
    archive = create_audit_archive(
        str(tmp_path / "audit.jsonl"), str(tmp_path / "archive")
    )
    manifest = json.loads(
        (tmp_path / "archive" / Path(archive["manifest_path"]).name).read_text()
    )
    (tmp_path / "archive" / manifest["segments"][0]["archived_file"]).unlink()

    verify_archive = _run_cli(
        [
            "audit",
            "--audit-path",
            str(tmp_path / "audit.jsonl"),
            "verify-archive",
            "--archive-manifest",
            archive["manifest_path"],
        ]
    )
    assert verify_archive.returncode != 0
    payload = json.loads(verify_archive.stdout)
    assert any("missing_archive_segment" in error for error in payload["errors"])


def test_registry_schema_status_and_upgrade_dry_run(tmp_path) -> None:
    db_path = tmp_path / "registry.db"
    base = ["registry", "--sqlite-path", str(db_path)]

    dry_run = _run_cli(base + ["upgrade", "--dry-run"])
    dry_run.check_returncode()
    dry_payload = json.loads(dry_run.stdout)
    assert dry_payload["status"] == "dry-run"
    assert dry_payload["pending_versions"]

    apply_result = _run_cli(base + ["upgrade"])
    apply_result.check_returncode()
    apply_payload = json.loads(apply_result.stdout)
    assert apply_payload["status"] == "ok"

    status = _run_cli(base + ["schema-status"])
    status.check_returncode()
    status_payload = json.loads(status.stdout)
    assert (
        status_payload["current_version"] == status_payload["latest_available_version"]
    )
    assert status_payload["pending_versions"] == []
