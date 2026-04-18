from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_CONNECTORS = {"jira", "servicenow"}


@dataclass(frozen=True)
class ScoreSignal:
    name: str
    score: int
    max_score: int
    required_min_score: int
    details: dict[str, Any]

    @property
    def gate_pass(self) -> bool:
        return self.score >= self.required_min_score


def _safe_read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _parse_python(path: Path) -> ast.AST | None:
    source = _safe_read(path)
    if not source.strip():
        return None
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def _test_function_names(path: Path) -> list[str]:
    tree = _parse_python(path)
    if tree is None:
        return []
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]


def _score_replay_supported_path_coverage(repo_root: Path) -> ScoreSignal:
    scenarios_dir = repo_root / "tests" / "replay_corpus" / "fixtures" / "scenarios"
    fixtures = sorted(scenarios_dir.glob("*.json")) if scenarios_dir.exists() else []

    connectors_seen: set[str] = set()
    supported_fixture_count = 0
    malformed: list[str] = []
    for fixture in fixtures:
        try:
            payload = json.loads(fixture.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            malformed.append(fixture.name)
            continue
        source_system = str(payload.get("input", {}).get("source_system", "")).lower().strip()
        if source_system in SUPPORTED_CONNECTORS:
            connectors_seen.add(source_system)
            supported_fixture_count += 1

    tests_file = repo_root / "tests" / "test_replay_corpus.py"
    replay_tests = _test_function_names(tests_file)

    checks = {
        "fixture_schema_dir_present": scenarios_dir.exists(),
        "supported_connectors_both_present": connectors_seen == SUPPORTED_CONNECTORS,
        "supported_fixture_count_at_least_two": supported_fixture_count >= 2,
        "replay_contract_tests_present": len(replay_tests) >= 2,
        "no_malformed_replay_fixtures": not malformed,
    }
    passed = sum(1 for value in checks.values() if value)
    score = round((passed / len(checks)) * 100)

    return ScoreSignal(
        name="replay_corpus_supported_path_coverage",
        score=score,
        max_score=100,
        required_min_score=100,
        details={
            "checks": checks,
            "supported_connectors_seen": sorted(connectors_seen),
            "supported_fixture_count": supported_fixture_count,
            "replay_tests": replay_tests,
            "malformed_fixture_files": malformed,
        },
    )


def _score_adversarial_audit_verification_coverage(repo_root: Path) -> ScoreSignal:
    test_path = repo_root / "tests" / "test_audit_chain_adversarial.py"
    source = _safe_read(test_path)
    test_names = _test_function_names(test_path)

    expected_categories = [
        "chain_link_mismatch",
        "duplicate_decision_id",
        "segment_sequence_gap",
        "manifest_segment_record_count_mismatch",
        "record_malformed_json",
        "signature_present_but_no_verifier",
    ]
    category_hits = {category: (category in source) for category in expected_categories}

    checks = {
        "adversarial_test_file_present": test_path.exists(),
        "adversarial_test_count_minimum": len(test_names) >= 6,
        "all_expected_verification_categories_asserted": all(category_hits.values()),
        "audit_chain_verifier_module_present": (
            repo_root / "src" / "sena" / "audit" / "chain.py"
        ).exists(),
    }

    passed = sum(1 for value in checks.values() if value)
    score = round((passed / len(checks)) * 100)

    return ScoreSignal(
        name="adversarial_audit_verification_coverage",
        score=score,
        max_score=100,
        required_min_score=100,
        details={
            "checks": checks,
            "adversarial_test_names": sorted(test_names),
            "category_hits": category_hits,
        },
    )


def _score_supported_path_e2e_coverage(repo_root: Path) -> ScoreSignal:
    test_path = repo_root / "tests" / "test_supported_integrations_e2e.py"
    source = _safe_read(test_path)
    test_names = _test_function_names(test_path)
    connectors_asserted = {name for name in SUPPORTED_CONNECTORS if f'"{name}"' in source}

    checks = {
        "supported_e2e_test_file_present": test_path.exists(),
        "supported_e2e_test_present": any("supported_connector_e2e" in name for name in test_names),
        "jira_and_servicenow_paths_exercised": connectors_asserted == SUPPORTED_CONNECTORS,
        "supported_mapping_fixtures_referenced": (
            "jira_mappings.yaml" in source and "servicenow_mappings.yaml" in source
        ),
    }
    passed = sum(1 for value in checks.values() if value)
    score = round((passed / len(checks)) * 100)

    return ScoreSignal(
        name="supported_path_end_to_end_test_coverage",
        score=score,
        max_score=100,
        required_min_score=100,
        details={
            "checks": checks,
            "connectors_asserted": sorted(connectors_asserted),
            "test_names": sorted(test_names),
        },
    )


def _score_backup_restore_verification_drill(repo_root: Path) -> ScoreSignal:
    drill_script = repo_root / "scripts" / "registry_backup_restore_drill.py"
    operations_test_path = repo_root / "tests" / "test_operations_scripts.py"
    dr_test_path = repo_root / "tests" / "test_policy_registry_disaster_recovery.py"

    dry_run_ok = False
    dry_run_payload: dict[str, Any] = {}
    if drill_script.exists():
        cmd = [
            sys.executable,
            str(drill_script),
            "--sqlite-path",
            "/tmp/policy.db",
            "--audit-chain",
            "/tmp/audit.jsonl",
            "--work-dir",
            "/tmp/sena-drill",
            "--dry-run",
        ]
        proc = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True, check=False)
        if proc.returncode == 0:
            try:
                dry_run_payload = json.loads(proc.stdout)
            except json.JSONDecodeError:
                dry_run_payload = {"raw_stdout": proc.stdout[-1000:]}
        dry_run_ok = proc.returncode == 0 and dry_run_payload.get("status") == "dry_run"
    else:
        proc = None

    operations_source = _safe_read(operations_test_path)
    dr_tests = _test_function_names(dr_test_path)

    checks = {
        "backup_restore_drill_script_present": drill_script.exists(),
        "drill_dry_run_executes": dry_run_ok,
        "drill_script_tests_present": "test_registry_backup_restore_drill_dry_run" in operations_source,
        "disaster_recovery_restore_tests_present": any("restore" in name for name in dr_tests),
    }
    passed = sum(1 for value in checks.values() if value)
    score = round((passed / len(checks)) * 100)

    return ScoreSignal(
        name="backup_restore_verification_drill",
        score=score,
        max_score=100,
        required_min_score=100,
        details={
            "checks": checks,
            "dry_run_status": dry_run_payload.get("status"),
            "dry_run_command_count": len(dry_run_payload.get("commands", []))
            if isinstance(dry_run_payload.get("commands"), list)
            else 0,
            "dry_run_stderr_tail": [] if proc is None else proc.stderr.strip().splitlines()[-10:],
            "disaster_recovery_test_names": sorted(dr_tests),
        },
    )


def _score_idempotency_conflict_handling(repo_root: Path) -> ScoreSignal:
    idempotency_tests = repo_root / "tests" / "test_idempotency.py"
    persistence_module = repo_root / "src" / "sena" / "integrations" / "persistence.py"
    source = _safe_read(idempotency_tests)
    persistence_source = _safe_read(persistence_module)

    checks = {
        "idempotency_test_file_present": idempotency_tests.exists(),
        "evaluate_conflict_asserts_409": (
            "test_evaluate_idempotency_key_conflicts_on_semantic_payload_change" in source
            and "== 409" in source
        ),
        "webhook_conflict_asserts_409": (
            "test_webhook_idempotency_key_conflicts_on_semantic_payload_change" in source
            and "idempotency_key_conflict" in source
        ),
        "persistence_layer_conflict_state_present": (
            'Literal["new", "duplicate", "conflict"]' in persistence_source
            and "conflict_count" in persistence_source
        ),
    }
    passed = sum(1 for value in checks.values() if value)
    score = round((passed / len(checks)) * 100)

    return ScoreSignal(
        name="idempotency_conflict_handling",
        score=score,
        max_score=100,
        required_min_score=100,
        details={"checks": checks},
    )


def _score_authorization_coverage_privileged_routes(repo_root: Path) -> ScoreSignal:
    authz_tests = repo_root / "tests" / "test_api_authz_security.py"
    source = _safe_read(authz_tests)

    privileged_routes = [
        "/v1/admin/data/payloads/1/hold",
        "/v1/audit/hold/dec_123",
        "/v1/integrations/jira/admin/outbound/dead-letter/replay",
        "/v1/integrations/jira/admin/outbound/dead-letter/manual-redrive",
        "/v1/bundle/promote",
    ]
    route_hits = {route: (route in source) for route in privileged_routes}

    checks = {
        "authz_security_test_file_present": authz_tests.exists(),
        "privileged_routes_explicitly_tested": all(route_hits.values()),
        "step_up_rejection_asserted": "step_up_auth_required" in source,
        "signed_step_up_assertion_validation_tested": "step_up_assertion_invalid" in source,
    }
    passed = sum(1 for value in checks.values() if value)
    score = round((passed / len(checks)) * 100)

    return ScoreSignal(
        name="authorization_coverage_on_privileged_routes",
        score=score,
        max_score=100,
        required_min_score=100,
        details={
            "checks": checks,
            "privileged_route_hits": route_hits,
            "test_names": sorted(_test_function_names(authz_tests)),
        },
    )


def _score_migration_safety_tests(repo_root: Path) -> ScoreSignal:
    registry_tests = repo_root / "tests" / "test_registry_migrations.py"
    failure_mode_tests = repo_root / "tests" / "test_failure_modes_and_migration_safety.py"
    migrations_dir = repo_root / "scripts" / "migrations"

    registry_source = _safe_read(registry_tests)
    failure_source = _safe_read(failure_mode_tests)
    migration_scripts = sorted(path.name for path in migrations_dir.glob("*.sql")) if migrations_dir.exists() else []

    checks = {
        "migration_scripts_present": len(migration_scripts) > 0,
        "checksum_mismatch_test_present": "test_checksum_mismatch_is_detected" in registry_source,
        "partial_failure_rollback_test_present": "test_partial_migration_failure_rolls_back_failed_step_only" in registry_source,
        "duplicate_version_guard_test_present": "duplicate migration versions" in failure_source,
        "legacy_fixture_forward_migration_test_present": "test_legacy_storage_state_fixture_migrates_forward" in failure_source,
    }
    passed = sum(1 for value in checks.values() if value)
    score = round((passed / len(checks)) * 100)

    return ScoreSignal(
        name="migration_safety_tests",
        score=score,
        max_score=100,
        required_min_score=100,
        details={
            "checks": checks,
            "migration_script_count": len(migration_scripts),
            "migration_scripts": migration_scripts,
        },
    )


def build_scorecard(repo_root: Path) -> dict[str, Any]:
    signals = [
        _score_replay_supported_path_coverage(repo_root),
        _score_adversarial_audit_verification_coverage(repo_root),
        _score_supported_path_e2e_coverage(repo_root),
        _score_backup_restore_verification_drill(repo_root),
        _score_idempotency_conflict_handling(repo_root),
        _score_authorization_coverage_privileged_routes(repo_root),
        _score_migration_safety_tests(repo_root),
    ]

    overall = round(sum(signal.score for signal in signals) / len(signals)) if signals else 0
    required_signals = [signal for signal in signals if signal.required_min_score > 0]
    failed_required = [signal.name for signal in required_signals if not signal.gate_pass]

    gate = {
        "decision": "GO" if not failed_required else "NO_GO",
        "failed_required_signals": failed_required,
        "required_signals": [
            {
                "name": signal.name,
                "required_min_score": signal.required_min_score,
                "score": signal.score,
                "pass": signal.gate_pass,
            }
            for signal in required_signals
        ],
        "note": "External validation should be blocked when any required hard-signal gate fails.",
    }

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository": repo_root.name,
        "scoring_model": {
            "type": "hard-signal-scorecard",
            "anti_metrics": [
                "raw_loc",
                "documentation_count",
                "total_test_count",
            ],
            "meaning": "Higher score means stronger evidence that supported-path controls are covered by executable checks.",
            "non_meaning": "Score does not prove enterprise-complete security/compliance or eliminate need for manual release review.",
        },
        "overall_score": overall,
        "gate": gate,
        "signals": [
            {
                "name": signal.name,
                "score": signal.score,
                "max_score": signal.max_score,
                "required_min_score": signal.required_min_score,
                "gate_pass": signal.gate_pass,
                "details": signal.details,
            }
            for signal in signals
        ],
    }


def render_markdown(scorecard: dict[str, Any]) -> str:
    lines = [
        "# SENA Hard-Signal Scorecard",
        "",
        f"- Generated (UTC): `{scorecard['generated_at_utc']}`",
        f"- Overall score: **{scorecard['overall_score']} / 100**",
        f"- External validation gate: **{scorecard['gate']['decision']}**",
        "",
        "## Gate outcome",
    ]

    failed = scorecard["gate"]["failed_required_signals"]
    if failed:
        lines.extend(["", "Required signals below threshold:"])
        lines.extend([f"- ❌ `{name}`" for name in failed])
    else:
        lines.extend(["", "- ✅ All required hard-signal gates passed."])

    lines.extend(["", "## Signal breakdown"])
    for signal in scorecard["signals"]:
        status = "✅" if signal["gate_pass"] else "❌"
        lines.append(
            f"- {status} `{signal['name']}`: {signal['score']}/{signal['max_score']} "
            f"(required ≥ {signal['required_min_score']})"
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "- This scorecard is a pre-validation engineering gate for the supported Jira + ServiceNow path.",
            "- It rewards executable evidence for replay determinism, adversarial audit verification, "
            "backup/restore drills, idempotency conflict handling, privileged-route authorization, and migration safety.",
            "- It is intentionally not a KPI dashboard for productivity or output volume.",
            "- A high score does not replace threat modeling, independent security review, legal/compliance review, "
            "or environment-specific operational approval.",
        ]
    )

    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute hard-signal engineering scorecard")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=ROOT,
        help="Repository root to inspect (defaults to current repository)",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=ROOT / "artifacts" / "maturity_scorecard.json",
        help="Path to write the JSON scorecard artifact",
    )
    parser.add_argument(
        "--output-markdown",
        type=Path,
        default=ROOT / "artifacts" / "maturity_scorecard.md",
        help="Path to write the Markdown scorecard report",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scorecard = build_scorecard(args.repo_root.resolve())

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(scorecard, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.write_text(render_markdown(scorecard), encoding="utf-8")

    print(json.dumps(scorecard, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
