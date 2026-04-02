from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
PYTHON = os.environ.get("PYTHON", sys.executable)


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    gate: str
    command: str | None
    remediation_hint: str
    details: dict[str, object]


def _run_command_check(*, name: str, gate: str, command: Sequence[str], remediation_hint: str, cwd: Path = ROOT) -> CheckResult:
    proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    stdout_lines = proc.stdout.strip().splitlines()
    stderr_lines = proc.stderr.strip().splitlines()
    return CheckResult(
        name=name,
        passed=proc.returncode == 0,
        gate=gate,
        command=" ".join(command),
        remediation_hint=remediation_hint,
        details={
            "return_code": proc.returncode,
            "stdout_tail": stdout_lines[-25:],
            "stderr_tail": stderr_lines[-25:],
        },
    )


def _docs_completeness_check() -> CheckResult:
    required_docs = {
        "docs/OPERATIONS.md": ["##", "oper"],
        "docs/DEPLOYMENT_PROFILES.md": ["##", "profile"],
        "docs/POLICY_LIFECYCLE.md": ["##", "promotion"],
        "docs/AUDIT_GUARANTEES.md": ["##", "verify"],
        "docs/DECISION_REVIEW_PACKAGES.md": ["##", "review"],
        "docs/integrations/JIRA.md": ["##", "jira"],
        "docs/integrations/SERVICENOW.md": ["##", "servicenow"],
        "docs/DESIGN_PARTNER_READY.md": ["##", "release gate"],
    }
    readme = (ROOT / "README.md").read_text(encoding="utf-8") if (ROOT / "README.md").exists() else ""

    missing: list[str] = []
    missing_keywords: dict[str, list[str]] = {}
    not_linked_from_readme: list[str] = []

    for rel_path, keywords in required_docs.items():
        path = ROOT / rel_path
        if not path.exists():
            missing.append(rel_path)
            continue
        content = path.read_text(encoding="utf-8").lower()
        expected = [kw for kw in keywords if kw.lower() not in content]
        if expected:
            missing_keywords[rel_path] = expected
        if rel_path not in readme:
            not_linked_from_readme.append(rel_path)

    passed = not (missing or missing_keywords or not_linked_from_readme)
    return CheckResult(
        name="operator_docs_completeness",
        passed=passed,
        gate="required",
        command=None,
        remediation_hint=(
            "Ensure all required onboarding docs exist, contain their expected sections, "
            "and are discoverable from README.md."
        ),
        details={
            "required_docs": sorted(required_docs),
            "missing_docs": missing,
            "docs_missing_keywords": missing_keywords,
            "docs_not_linked_from_readme": not_linked_from_readme,
        },
    )


def run_all_checks() -> list[CheckResult]:
    checks = [
        _run_command_check(
            name="flagship_workflows_end_to_end",
            gate="required",
            command=[PYTHON, "-m", "pytest", "tests/test_flagship_workflows.py", "tests/test_design_partner_reference.py"],
            remediation_hint="Fix failing workflow fixtures or orchestration logic before release.",
        ),
        _run_command_check(
            name="evidence_pack_generation",
            gate="required",
            command=[
                PYTHON,
                "scripts/generate_evidence_pack.py",
                "--output-dir",
                ".design_partner_tmp/evidence_pack",
                "--output-zip",
                ".design_partner_tmp/evidence_pack.zip",
                "--clean",
            ],
            remediation_hint=(
                "Repair evidence pack inputs under examples/design_partner_reference and "
                "ensure artifacts build deterministically."
            ),
        ),
        _run_command_check(
            name="audit_verification",
            gate="required",
            command=[PYTHON, "-m", "pytest", "tests/test_audit_chain_and_schema.py", "tests/test_audit_sinks.py"],
            remediation_hint="Resolve audit chain/sink validation failures before promotion.",
        ),
        _run_command_check(
            name="simulation_gate_enforcement",
            gate="required",
            command=[PYTHON, "-m", "pytest", "tests/test_lifecycle_and_simulation.py"],
            remediation_hint="Update lifecycle gate logic or simulation fixtures so failing bundles cannot be promoted.",
        ),
        _run_command_check(
            name="backup_restore_success",
            gate="required",
            command=[PYTHON, "-m", "pytest", "tests/test_policy_registry_disaster_recovery.py"],
            remediation_hint="Fix backup/restore flow and migration compatibility before release.",
        ),
        _run_command_check(
            name="replay_drift_analysis",
            gate="required",
            command=[PYTHON, "-m", "pytest", "tests/test_replay_drift.py"],
            remediation_hint="Repair replay determinism and drift detection baselines.",
        ),
        _docs_completeness_check(),
    ]
    return checks


def _render_text_report(results: list[CheckResult]) -> str:
    lines = ["DESIGN PARTNER READINESS REPORT", "=" * 32]
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        lines.append(f"- [{status}] {result.name} (gate={result.gate})")
        if result.command:
            lines.append(f"    command: {result.command}")
        if not result.passed:
            lines.append(f"    remediation: {result.remediation_hint}")
            lines.append(f"    details: {json.dumps(result.details, sort_keys=True)}")
    total = len(results)
    failed = sum(1 for result in results if not result.passed)
    lines.append("")
    lines.append(f"Summary: {total - failed}/{total} checks passed.")
    lines.append("Release gate: PASS" if failed == 0 else "Release gate: FAIL")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run design-partner readiness checks and release gates")
    parser.add_argument(
        "--output-json",
        type=Path,
        default=ROOT / "artifacts" / "design_partner_readiness.json",
        help="Path to write machine-readable check results",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results = run_all_checks()
    payload = {
        "all_passed": all(result.passed for result in results),
        "results": [asdict(result) for result in results],
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(_render_text_report(results))
    raise SystemExit(0 if payload["all_passed"] else 1)


if __name__ == "__main__":
    main()
