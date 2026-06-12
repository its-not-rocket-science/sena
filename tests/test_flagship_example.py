from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_flagship_example_runs_and_produces_artifacts(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    target_examples = tmp_path / "examples"
    shutil.copytree(repo_root / "examples" / "flagship", target_examples / "flagship")
    shutil.copytree(
        repo_root / "examples" / "design_partner_reference",
        target_examples / "design_partner_reference",
    )

    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root / "src")
    subprocess.run(
        [sys.executable, str(target_examples / "flagship" / "run_flagship.py")],
        check=True,
        env=env,
    )

    summary = json.loads(
        (target_examples / "flagship" / "artifacts" / "summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["actual_outcome"] == "BLOCKED"

    audit = json.loads(
        (
            target_examples
            / "flagship"
            / "artifacts"
            / "audit-verification.json"
        ).read_text(encoding="utf-8")
    )
    assert audit["valid"] is True


def test_flagship_cli_payload_blocks_emergency_privileged_change() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sena.cli.main",
            str(repo_root / "examples" / "flagship" / "evaluate_payload.json"),
            "--policy-dir",
            str(
                repo_root
                / "examples"
                / "design_partner_reference"
                / "policy_bundles"
                / "active"
            ),
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(repo_root / "src")},
    )
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "BLOCKED"
