from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class GuardrailArea:
    name: str
    paths: tuple[str, ...]
    max_file_loc: int
    max_concentration_ratio: float
    max_branch_density: float


GUARDRAILS: tuple[GuardrailArea, ...] = (
    GuardrailArea(
        name="evaluator",
        paths=(
            "src/sena/engine/evaluator.py",
            "src/sena/engine/evaluator_components.py",
        ),
        max_file_loc=760,
        max_concentration_ratio=0.66,
        max_branch_density=5.2,
    ),
    GuardrailArea(
        name="api_app_runtime_wiring",
        paths=(
            "src/sena/api/app.py",
            "src/sena/api/runtime.py",
            "src/sena/api/dependencies.py",
        ),
        max_file_loc=730,
        max_concentration_ratio=0.73,
        max_branch_density=5.5,
    ),
    GuardrailArea(
        name="policy_store_migrations",
        paths=(
            "src/sena/policy/store.py",
            "src/sena/policy/migrations.py",
            "scripts/migrate_policy_registry.py",
            "scripts/migrations/*.sql",
        ),
        max_file_loc=760,
        max_concentration_ratio=0.75,
        max_branch_density=4.7,
    ),
    GuardrailArea(
        name="integration_connectors",
        paths=(
            "src/sena/integrations/jira.py",
            "src/sena/integrations/jira_client.py",
            "src/sena/integrations/servicenow.py",
            "src/sena/integrations/servicenow_client.py",
            "src/sena/integrations/approval.py",
            "src/sena/integrations/persistence.py",
            "src/sena/integrations/registry.py",
        ),
        max_file_loc=730,
        max_concentration_ratio=0.40,
        max_branch_density=4.2,
    ),
)


def _resolve_paths(patterns: tuple[str, ...]) -> list[Path]:
    files: set[Path] = set()
    for pattern in patterns:
        matched = list(ROOT.glob(pattern))
        if not matched:
            continue
        for path in matched:
            if path.is_file() and path.suffix in {".py", ".sql"}:
                files.add(path)
    return sorted(files)


def _loc(path: Path) -> int:
    lines = 0
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if path.suffix == ".py" and line.startswith("#"):
            continue
        if path.suffix == ".sql" and line.startswith("--"):
            continue
        lines += 1
    return lines


def _python_complexity(path: Path) -> dict[str, float]:
    if path.suffix != ".py":
        return {"functions": 0, "branches": 0, "branch_density": 0.0}

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return {"functions": 0, "branches": 0, "branch_density": 0.0}

    functions = 0
    branches = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions += 1
        if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.Match, ast.BoolOp)):
            branches += 1

    branch_density = (branches / functions) if functions else float(branches)
    return {
        "functions": functions,
        "branches": branches,
        "branch_density": round(branch_density, 3),
    }


def _measure_area(area: GuardrailArea) -> dict[str, Any]:
    files = _resolve_paths(area.paths)
    measured_files: list[dict[str, Any]] = []
    for path in files:
        loc = _loc(path)
        complexity = _python_complexity(path)
        measured_files.append(
            {
                "path": str(path.relative_to(ROOT)),
                "loc": loc,
                **complexity,
            }
        )

    measured_files.sort(key=lambda item: item["loc"], reverse=True)
    total_loc = sum(item["loc"] for item in measured_files)
    largest = measured_files[0] if measured_files else None
    concentration_ratio = (largest["loc"] / total_loc) if largest and total_loc else 0.0

    violations: list[str] = []
    if largest and largest["loc"] > area.max_file_loc:
        violations.append(
            f"largest file {largest['path']} has {largest['loc']} LOC (max {area.max_file_loc})"
        )
    if concentration_ratio > area.max_concentration_ratio:
        violations.append(
            f"largest file concentration {concentration_ratio:.3f} exceeds {area.max_concentration_ratio:.3f}"
        )

    hotspot_files = [
        file
        for file in measured_files
        if file["path"].endswith(".py")
        and file["functions"] > 0
        and file["branch_density"] > area.max_branch_density
    ]
    for hotspot in hotspot_files:
        violations.append(
            f"complexity hotspot {hotspot['path']} branch density {hotspot['branch_density']:.3f} exceeds {area.max_branch_density:.3f}"
        )

    top_hotspots = sorted(
        [file for file in measured_files if file["path"].endswith(".py") and file["functions"] > 0],
        key=lambda item: item["branch_density"],
        reverse=True,
    )[:3]

    return {
        "area": area.name,
        "thresholds": {
            "max_file_loc": area.max_file_loc,
            "max_concentration_ratio": area.max_concentration_ratio,
            "max_branch_density": area.max_branch_density,
        },
        "budget_remaining": {
            "file_loc": (area.max_file_loc - largest["loc"]) if largest else area.max_file_loc,
            "concentration_ratio": round(area.max_concentration_ratio - concentration_ratio, 3),
        },
        "summary": {
            "files": len(measured_files),
            "total_loc": total_loc,
            "largest_file": largest["path"] if largest else None,
            "largest_file_loc": largest["loc"] if largest else 0,
            "largest_file_concentration_ratio": round(concentration_ratio, 3),
            "violation_count": len(violations),
        },
        "files": measured_files,
        "top_complexity_hotspots": top_hotspots,
        "violations": violations,
    }


def generate_report() -> dict[str, Any]:
    areas = [_measure_area(area) for area in GUARDRAILS]
    total_violations = sum(len(area["violations"]) for area in areas)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repository_root": str(ROOT),
        "status": "fail" if total_violations else "pass",
        "guardrail_areas": areas,
        "violation_count": total_violations,
        "notes": [
            "LOC is non-empty, non-comment lines.",
            "Branch density is AST branch nodes per function for Python files only.",
            "Guardrails are intentionally coarse to signal module concentration risk, not quality scores.",
        ],
    }


def _print_summary(report: dict[str, Any]) -> None:
    print("architecture concentration guardrails")
    print(f"status: {report['status']} (violations={report['violation_count']})")
    for area in report["guardrail_areas"]:
        summary = area["summary"]
        print(
            "- "
            f"{area['area']}: files={summary['files']} total_loc={summary['total_loc']} "
            f"largest={summary['largest_file']}({summary['largest_file_loc']}) "
            f"concentration={summary['largest_file_concentration_ratio']:.3f} "
            f"violations={summary['violation_count']}"
        )
        for violation in area["violations"]:
            print(f"  ! {violation}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Flag coarse file-size and complexity concentration risk in core supported SENA modules."
        )
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional path to persist full JSON report.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Return non-zero exit code when any guardrail is violated.",
    )
    args = parser.parse_args()

    report = generate_report()
    _print_summary(report)

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    if args.check and report["violation_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
