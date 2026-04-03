from __future__ import annotations

import argparse
import ast
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
DEFAULT_OUTPUT_DIR = ROOT / "docs" / "examples" / "pilot_evidence_sample"


@dataclass(frozen=True)
class CriterionResult:
    id: str
    description: str
    threshold: str
    measured: str
    passed: bool
    evidence: list[str]


def _write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_command(command: list[str], output_path: Path) -> dict[str, Any]:
    proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    payload = {
        "command": " ".join(command),
        "return_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
    _write_json(output_path, payload)
    return payload


def _render_benchmark_summary(criteria: list[CriterionResult]) -> str:
    lines = [
        "# Pilot benchmark evidence: SENA vs embedded workflow rules",
        "",
        "Chosen use case: high-risk enterprise change approvals normalized across Jira and ServiceNow.",
        "",
        "## Why SENA is better (artifact-backed)",
        "",
        "- **Explainability**: `benchmark/sena/review_packages.json` contains deterministic review packages with matched rules and rationale per decision.",
        "- **Policy portability**: `benchmark/cross_system_reuse.json` shows one policy bundle reused across Jira and ServiceNow fixtures.",
        "- **Release control**: `benchmark/promotion_governance.json` demonstrates promotion passes only with required validation evidence and fails without it.",
        "- **Replayability**: `benchmark/sena/replayability.json` records repeated evaluations with stable `decision_hash` values.",
        "- **Audit evidence**: `benchmark/sena/audit_summary.json` and `benchmark/sena/audit/sena_audit.jsonl` provide tamper-evident chain verification.",
        "",
        "## Acceptance criteria snapshot",
        "",
    ]
    for item in criteria:
        status = "PASS" if item.passed else "FAIL"
        lines.append(
            f"- [{status}] **{item.id}** — measured `{item.measured}` against threshold `{item.threshold}`."
        )
    lines.append("")
    lines.append("Regenerate this bundle with `make pilot-evidence`.")
    return "\n".join(lines) + "\n"


def _api_error_shape_stability_check(output_path: Path) -> dict[str, Any]:
    source = (ROOT / "src" / "sena" / "api" / "errors.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    catalog_node = None
    for node in module.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "ERROR_CODE_CATALOG":
            catalog_node = node.value
            break
    if catalog_node is None:
        payload = {
            "check": "api_error_shape_stability",
            "return_code": 1,
            "error": "ERROR_CODE_CATALOG not found",
        }
        _write_json(output_path, payload)
        return payload

    catalog: dict[str, dict[str, Any]] = {}
    if not isinstance(catalog_node, ast.Dict):
        payload = {
            "check": "api_error_shape_stability",
            "return_code": 1,
            "error": "ERROR_CODE_CATALOG is not a dictionary literal",
        }
        _write_json(output_path, payload)
        return payload

    for key_node, value_node in zip(catalog_node.keys, catalog_node.values):
        if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
            continue
        if not isinstance(value_node, ast.Call) or not value_node.args:
            continue
        status_node = value_node.args[0]
        message_node = value_node.args[1] if len(value_node.args) > 1 else None
        if not isinstance(status_node, ast.Constant) or not isinstance(status_node.value, int):
            continue
        if not isinstance(message_node, ast.Constant) or not isinstance(message_node.value, str):
            continue
        catalog[key_node.value] = {
            "http_status": status_node.value,
            "message": message_node.value,
        }

    canonical = json.dumps(catalog, indent=2, sort_keys=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    baseline_file = ROOT / "docs" / "examples" / "pilot_baselines" / "api_error_catalog_sha256.txt"
    expected = baseline_file.read_text(encoding="utf-8").strip() if baseline_file.exists() else ""
    passed = bool(expected) and digest == expected
    payload = {
        "check": "api_error_shape_stability",
        "return_code": 0 if passed else 1,
        "catalog_entries": len(catalog),
        "catalog_sha256": digest,
        "baseline_sha256": expected,
        "passed": passed,
        "baseline_file": str(baseline_file.relative_to(ROOT)),
    }
    _write_json(output_path, payload)
    return payload


def generate(output_dir: Path, clean: bool) -> dict[str, Any]:
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    checks_dir = output_dir / "checks"
    benchmark_dir = output_dir / "benchmark"
    evidence_pack_dir = output_dir / "evidence_pack"

    benchmark_run = _run_command(
        [
            PYTHON,
            "scripts/benchmark_embedded_rules_vs_sena.py",
            "--output-dir",
            str(benchmark_dir),
            "--clean",
        ],
        checks_dir / "benchmark_command.json",
    )
    evidence_pack_run = _run_command(
        [
            PYTHON,
            "scripts/generate_evidence_pack.py",
            "--output-dir",
            str(evidence_pack_dir),
            "--clean",
        ],
        checks_dir / "evidence_pack_command.json",
    )
    api_shape_run = _api_error_shape_stability_check(checks_dir / "api_error_shape_stability.json")
    restore_run = _run_command(
        [PYTHON, "-m", "pytest", "tests/test_policy_registry_disaster_recovery.py"],
        checks_dir / "restore_drill.json",
    )

    summary = json.loads((benchmark_dir / "summary.json").read_text(encoding="utf-8"))
    replay_rows = json.loads((benchmark_dir / "sena" / "replayability.json").read_text(encoding="utf-8"))
    promotion = json.loads((benchmark_dir / "promotion_governance.json").read_text(encoding="utf-8"))
    cross_system = json.loads((benchmark_dir / "cross_system_reuse.json").read_text(encoding="utf-8"))
    audit_summary = json.loads((benchmark_dir / "sena" / "audit_summary.json").read_text(encoding="utf-8"))

    replay_success = sum(1 for row in replay_rows if row.get("deterministic_replay"))
    replay_total = len(replay_rows)
    replay_rate = replay_success / replay_total if replay_total else 0.0

    promotion_checks = [
        promotion["sena_with_required_artifacts"].get("valid") is True,
        promotion["sena_without_required_artifacts"].get("valid") is False,
    ]
    promotion_coverage = sum(1 for passed in promotion_checks if passed) / len(promotion_checks)

    criteria = [
        CriterionResult(
            id="deterministic_replay_success_rate",
            description="Repeated evaluations for identical inputs should produce stable outcomes and decision hashes.",
            threshold="1.00",
            measured=f"{replay_rate:.2f}",
            passed=replay_rate >= 1.00,
            evidence=["benchmark/sena/replayability.json"],
        ),
        CriterionResult(
            id="promotion_gate_coverage",
            description="Promotion gates must enforce allow-with-artifacts and deny-without-artifacts paths.",
            threshold=">= 0.90",
            measured=f"{promotion_coverage:.2f}",
            passed=promotion_coverage >= 0.90,
            evidence=["benchmark/promotion_governance.json"],
        ),
        CriterionResult(
            id="audit_verification_pass_rate",
            description="Generated audit chain must verify as valid.",
            threshold="1.00",
            measured="1.00" if audit_summary.get("valid") else "0.00",
            passed=bool(audit_summary.get("valid")),
            evidence=["benchmark/sena/audit_summary.json", "benchmark/sena/audit/sena_audit.jsonl"],
        ),
        CriterionResult(
            id="api_error_shape_stability",
            description="API error contract tests should pass to keep response shapes stable.",
            threshold="1.00",
            measured="1.00" if api_shape_run["return_code"] == 0 else "0.00",
            passed=api_shape_run["return_code"] == 0,
            evidence=["checks/api_error_shape_stability.json"],
        ),
        CriterionResult(
            id="restore_drill_success",
            description="Disaster recovery drill tests must pass.",
            threshold="1.00",
            measured="1.00" if restore_run["return_code"] == 0 else "0.00",
            passed=restore_run["return_code"] == 0,
            evidence=["checks/restore_drill.json"],
        ),
        CriterionResult(
            id="integration_fixture_coverage",
            description="Pilot fixture set must include Jira and ServiceNow integration fixtures.",
            threshold="fixtures >= 5 and systems >= 2",
            measured=(
                f"fixtures={len(cross_system.get('input_fixtures', []))},"
                f" systems={len(cross_system.get('source_systems', []))}"
            ),
            passed=len(cross_system.get("input_fixtures", [])) >= 5 and len(cross_system.get("source_systems", [])) >= 2,
            evidence=["benchmark/cross_system_reuse.json"],
        ),
    ]

    benchmark_md = _render_benchmark_summary(criteria)
    (output_dir / "BENCHMARK_EVIDENCE.md").write_text(benchmark_md, encoding="utf-8")

    result = {
        "all_passed": all(item.passed for item in criteria),
        "criteria": [asdict(item) for item in criteria],
        "bundle_root": str(output_dir.resolve().relative_to(ROOT)),
        "commands": {
            "benchmark": benchmark_run,
            "evidence_pack": evidence_pack_run,
            "api_error_shape": api_shape_run,
            "restore_drill": restore_run,
        },
        "benchmark_summary": summary,
    }
    _write_json(output_dir / "pilot_acceptance_results.json", result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate reproducible pilot-readiness evidence bundle")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--clean", action="store_true", help="Delete output directory before generation")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = generate(output_dir=args.output_dir, clean=args.clean)
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["all_passed"] else 1)


if __name__ == "__main__":
    main()
