from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class MetricScore:
    name: str
    score: int
    max_score: int
    details: dict[str, Any]


def _safe_read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _python_files(base: Path) -> list[Path]:
    if not base.exists():
        return []
    return sorted(path for path in base.rglob("*.py") if path.is_file())


def _non_empty_non_comment_lines(path: Path) -> int:
    count = 0
    for raw_line in _safe_read(path).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        count += 1
    return count


def _collect_test_names(tests_root: Path) -> list[str]:
    names: list[str] = []
    for file_path in _python_files(tests_root):
        source = _safe_read(file_path)
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                names.append(node.name)
    return names


def _score_api_layer_complexity(repo_root: Path) -> MetricScore:
    api_files = _python_files(repo_root / "src" / "sena" / "api")
    if not api_files:
        return MetricScore(
            name="api_layer_complexity_file_concentration",
            score=0,
            max_score=100,
            details={"reason": "No API files discovered"},
        )

    file_line_counts = {str(path.relative_to(repo_root)): _non_empty_non_comment_lines(path) for path in api_files}
    total_lines = sum(file_line_counts.values())
    largest_file = max(file_line_counts.items(), key=lambda x: x[1])
    concentration = (largest_file[1] / total_lines) if total_lines else 1.0

    branches = 0
    functions = 0
    for file_path in api_files:
        try:
            tree = ast.parse(_safe_read(file_path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions += 1
            if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Match, ast.Try, ast.BoolOp)):
                branches += 1

    avg_branch_density = (branches / functions) if functions else float(branches)

    concentration_score = max(0.0, 1.0 - max(0.0, concentration - 0.15) / 0.45)
    complexity_score = max(0.0, 1.0 - max(0.0, avg_branch_density - 2.0) / 5.0)
    final_score = round(100 * ((concentration_score * 0.6) + (complexity_score * 0.4)))

    return MetricScore(
        name="api_layer_complexity_file_concentration",
        score=final_score,
        max_score=100,
        details={
            "total_api_files": len(api_files),
            "total_api_non_comment_loc": total_lines,
            "largest_file": {"path": largest_file[0], "loc": largest_file[1]},
            "largest_file_concentration_ratio": round(concentration, 4),
            "branch_nodes": branches,
            "function_nodes": functions,
            "avg_branch_density": round(avg_branch_density, 4),
            "scoring_model": "higher score favors distributed API surface and lower branch density",
        },
    )


def _score_service_layer_coverage(repo_root: Path) -> MetricScore:
    services = _python_files(repo_root / "src" / "sena" / "services")
    tests = _python_files(repo_root / "tests")
    tests_text = "\n".join(_safe_read(path) for path in tests)

    covered = []
    missing = []
    for service_file in services:
        if service_file.name == "__init__.py":
            continue
        module_name = service_file.stem
        dotted = f"sena.services.{module_name}"
        if module_name in tests_text or dotted in tests_text:
            covered.append(str(service_file.relative_to(repo_root)))
        else:
            missing.append(str(service_file.relative_to(repo_root)))

    considered = len(covered) + len(missing)
    ratio = (len(covered) / considered) if considered else 0.0
    score = round(100 * ratio)
    return MetricScore(
        name="service_layer_coverage",
        score=score,
        max_score=100,
        details={
            "services_considered": considered,
            "services_referenced_by_tests": len(covered),
            "coverage_ratio": round(ratio, 4),
            "covered_services": covered,
            "missing_service_references": missing,
        },
    )


def _score_failure_mode_test_count(repo_root: Path) -> MetricScore:
    test_names = _collect_test_names(repo_root / "tests")
    pattern = re.compile(r"(fail|error|invalid|unsupported|drift|disaster|recovery|guard)")
    matching = sorted(name for name in test_names if pattern.search(name))
    target = 30
    score = min(100, round((len(matching) / target) * 100))
    return MetricScore(
        name="failure_mode_test_count",
        score=score,
        max_score=100,
        details={
            "matching_tests": len(matching),
            "target_for_full_score": target,
            "examples": matching[:25],
        },
    )


def _score_migration_coverage(repo_root: Path) -> MetricScore:
    migrations = sorted((repo_root / "scripts" / "migrations").glob("*.sql"))
    tests_text = "\n".join(_safe_read(path) for path in _python_files(repo_root / "tests"))

    covered = []
    missing = []
    for migration in migrations:
        if migration.name in tests_text or migration.stem in tests_text:
            covered.append(migration.name)
        else:
            missing.append(migration.name)

    ratio = (len(covered) / len(migrations)) if migrations else 0.0
    score = round(100 * ratio)
    return MetricScore(
        name="migration_coverage",
        score=score,
        max_score=100,
        details={
            "migration_scripts": len(migrations),
            "covered_migrations": covered,
            "missing_migrations": missing,
            "coverage_ratio": round(ratio, 4),
        },
    )


def _score_persistence_audit_recovery_coverage(repo_root: Path) -> MetricScore:
    tests_text = "\n".join(_safe_read(path) for path in _python_files(repo_root / "tests"))

    source_checks = {
        "policy_disaster_recovery": (repo_root / "src" / "sena" / "policy" / "disaster_recovery.py").exists(),
        "audit_chain": (repo_root / "src" / "sena" / "audit" / "chain.py").exists(),
        "audit_sinks": (repo_root / "src" / "sena" / "audit" / "sinks.py").exists(),
        "persistence_architecture_doc": (repo_root / "docs" / "PERSISTENCE_ARCHITECTURE.md").exists(),
        "audit_guarantees_doc": (repo_root / "docs" / "AUDIT_GUARANTEES.md").exists(),
    }

    test_checks = {
        "test_policy_registry_disaster_recovery": "test_policy_registry_disaster_recovery" in tests_text,
        "test_audit_chain": "test_audit_chain" in tests_text,
        "test_audit_sinks": "test_audit_sinks" in tests_text,
        "test_persistence_architecture": "test_persistence_architecture" in tests_text,
    }

    checks = {**source_checks, **test_checks}
    passed = sum(1 for value in checks.values() if value)
    total = len(checks)
    score = round((passed / total) * 100)

    return MetricScore(
        name="persistence_audit_recovery_coverage",
        score=score,
        max_score=100,
        details={"checks": checks, "passed": passed, "total": total},
    )


def _score_documentation_completeness(repo_root: Path) -> MetricScore:
    required_docs = [
        "docs/ARCHITECTURE.md",
        "docs/CONTROL_PLANE.md",
        "docs/POLICY_LIFECYCLE.md",
        "docs/DECISION_REVIEW_PACKAGES.md",
        "docs/examples/portable_policy_pack_jira_servicenow.md",
        "docs/MIGRATION.md",
    ]
    readme_text = _safe_read(repo_root / "README.md")

    doc_results: dict[str, bool] = {}
    for rel_path in required_docs:
        path = repo_root / rel_path
        exists = path.exists()
        linked_in_readme = rel_path in readme_text
        doc_results[rel_path] = exists and linked_in_readme

    passed = sum(1 for ok in doc_results.values() if ok)
    score = round((passed / len(required_docs)) * 100)

    return MetricScore(
        name="documentation_completeness_flagship_workflows",
        score=score,
        max_score=100,
        details={
            "required_docs": required_docs,
            "docs_present_and_linked_from_readme": doc_results,
            "passed": passed,
            "total": len(required_docs),
            "note": "requires docs to exist and be discoverable from README",
        },
    )


def _score_evidence_pack_generation_success(repo_root: Path) -> MetricScore:
    output_dir = repo_root / ".maturity_tmp" / "evidence_pack"
    output_zip = repo_root / ".maturity_tmp" / "evidence_pack.zip"
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        os.environ.get("PYTHON", "python"),
        str(repo_root / "scripts" / "generate_evidence_pack.py"),
        "--output-dir",
        str(output_dir),
        "--output-zip",
        str(output_zip),
        "--clean",
    ]
    proc = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True, check=False)
    success = proc.returncode == 0 and output_zip.exists()
    score = 100 if success else 0

    stdout = proc.stdout.strip().splitlines()
    stderr = proc.stderr.strip().splitlines()
    return MetricScore(
        name="evidence_pack_generation_success",
        score=score,
        max_score=100,
        details={
            "command": " ".join(cmd),
            "return_code": proc.returncode,
            "output_zip_exists": output_zip.exists(),
            "stdout_tail": stdout[-10:],
            "stderr_tail": stderr[-10:],
        },
    )


def _score_replay_drift_coverage(repo_root: Path) -> MetricScore:
    tests_text = "\n".join(_safe_read(path) for path in _python_files(repo_root / "tests"))
    scenarios = sorted((repo_root / "src" / "sena" / "examples" / "scenarios").glob("*.json"))

    checks = {
        "replay_drift_tests_present": "replay" in tests_text and "drift" in tests_text,
        "explicit_replay_drift_test_file": (repo_root / "tests" / "test_replay_drift.py").exists(),
        "ai_assisted_scenarios_present": any("ai_assisted" in path.name for path in scenarios),
        "simulation_scenarios_fixture_present": any("simulation_scenarios" in path.name for path in scenarios),
    }

    passed = sum(1 for value in checks.values() if value)
    total = len(checks)
    score = round((passed / total) * 100)

    return MetricScore(
        name="replay_drift_coverage_ai_assisted_actions",
        score=score,
        max_score=100,
        details={"checks": checks, "passed": passed, "total": total},
    )


def build_scorecard(repo_root: Path) -> dict[str, Any]:
    metrics = [
        _score_api_layer_complexity(repo_root),
        _score_service_layer_coverage(repo_root),
        _score_failure_mode_test_count(repo_root),
        _score_migration_coverage(repo_root),
        _score_persistence_audit_recovery_coverage(repo_root),
        _score_documentation_completeness(repo_root),
        _score_evidence_pack_generation_success(repo_root),
        _score_replay_drift_coverage(repo_root),
    ]

    weighted = [metric.score for metric in metrics]
    overall = round(sum(weighted) / len(weighted)) if weighted else 0

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository": repo_root.name,
        "scoring_principles": {
            "objective": "all metrics are computed from repository files, AST analysis, and executable scripts",
            "anti_vanity": "scores prioritize coverage signals and operational checks over raw line counts",
            "architecture_nudge": "metrics favor supported src/sena architecture, tests, docs, and deterministic release evidence",
        },
        "overall_score": overall,
        "metrics": [
            {
                "name": metric.name,
                "score": metric.score,
                "max_score": metric.max_score,
                "details": metric.details,
            }
            for metric in metrics
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute repository maturity scorecard")
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scorecard = build_scorecard(args.repo_root.resolve())

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(scorecard, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(scorecard, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
