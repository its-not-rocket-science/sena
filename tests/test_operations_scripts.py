import json
import subprocess
import sys


def _run_script(args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_registry_backup_restore_drill_dry_run() -> None:
    result = _run_script(
        [
            "scripts/registry_backup_restore_drill.py",
            "--sqlite-path",
            "/tmp/policy.db",
            "--audit-chain",
            "/tmp/audit.jsonl",
            "--work-dir",
            "/tmp/sena-drill",
            "--dry-run",
        ]
    )
    result.check_returncode()
    payload = json.loads(result.stdout)
    assert payload["status"] == "dry_run"
    assert len(payload["commands"]) == 3
    assert payload["commands"][0][3] == "registry"
    assert payload["commands"][2][-2] == "--audit-chain"


def test_dead_letter_admin_dry_run_list() -> None:
    result = _run_script(
        [
            "scripts/dead_letter_admin.py",
            "--base-url",
            "http://127.0.0.1:8000",
            "--connector",
            "jira",
            "--api-key",
            "test-key",
            "--dry-run",
            "list",
            "--limit",
            "10",
        ]
    )
    result.check_returncode()
    payload = json.loads(result.stdout)
    assert payload["status"] == "dry_run"
    assert payload["method"] == "GET"
    assert payload["url"].endswith("/dead-letter?limit=10")


def test_dead_letter_admin_dry_run_manual_redrive() -> None:
    result = _run_script(
        [
            "scripts/dead_letter_admin.py",
            "--base-url",
            "http://127.0.0.1:8000",
            "--connector",
            "servicenow",
            "--api-key",
            "test-key",
            "--dry-run",
            "manual-redrive",
            "--ids",
            "5",
            "6",
            "--note",
            "INC-42",
        ]
    )
    result.check_returncode()
    payload = json.loads(result.stdout)
    assert payload["status"] == "dry_run"
    assert payload["method"] == "POST"
    assert payload["body"] == {"ids": [5, 6], "note": "INC-42"}


def test_architecture_concentration_guardrails_report() -> None:
    result = _run_script(
        [
            "scripts/check_architecture_concentration.py",
        ]
    )
    result.check_returncode()
    assert "architecture concentration guardrails" in result.stdout
    assert "evaluator" in result.stdout


def test_architecture_concentration_guardrails_check_with_output_json(tmp_path) -> None:
    output = tmp_path / "architecture_concentration.json"
    result = _run_script(
        [
            "scripts/check_architecture_concentration.py",
            "--check",
            "--output-json",
            str(output),
        ]
    )
    result.check_returncode()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "pass"
    assert payload["violation_count"] == 0
    assert payload["guardrail_areas"]
