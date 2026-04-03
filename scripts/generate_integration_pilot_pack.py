from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
DEFAULT_OUTPUT_DIR = ROOT / "docs" / "examples" / "pilot_integration_pack"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run(command: list[str], output_path: Path) -> dict[str, Any]:
    proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    payload = {
        "command": " ".join(command),
        "return_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
    _write_json(output_path, payload)
    return payload


def generate(output_dir: Path, clean: bool) -> dict[str, Any]:
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    checks_dir = output_dir / "checks"
    artifacts_dir = output_dir / "artifacts"

    run_reference = _run(
        [PYTHON, "examples/design_partner_reference/run_reference.py"],
        checks_dir / "design_partner_reference.json",
    )
    pilot_evidence = _run(
        [
            PYTHON,
            "scripts/generate_pilot_evidence.py",
            "--output-dir",
            str(artifacts_dir / "pilot_evidence"),
            "--clean",
        ],
        checks_dir / "pilot_evidence.json",
    )

    design_partner_artifacts = ROOT / "examples" / "design_partner_reference" / "artifacts"
    if design_partner_artifacts.exists():
        shutil.copytree(design_partner_artifacts, artifacts_dir / "design_partner_reference", dirs_exist_ok=True)

    required_paths = [
        artifacts_dir / "design_partner_reference" / "promotion-validation.json",
        artifacts_dir / "design_partner_reference" / "audit-chain-verification.json",
        artifacts_dir / "design_partner_reference" / "normalized-event-examples.json",
        artifacts_dir / "pilot_evidence" / "pilot_acceptance_results.json",
    ]
    missing = [str(path.relative_to(output_dir)) for path in required_paths if not path.exists()]

    summary = {
        "all_passed": run_reference["return_code"] == 0 and pilot_evidence["return_code"] == 0 and not missing,
        "missing_required_artifacts": missing,
        "commands": {
            "run_reference": run_reference,
            "pilot_evidence": pilot_evidence,
        },
    }
    _write_json(output_dir / "integration_pack_summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate end-to-end pilot integration evidence pack")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--clean", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = generate(output_dir=args.output_dir, clean=args.clean)
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["all_passed"] else 1)


if __name__ == "__main__":
    main()
