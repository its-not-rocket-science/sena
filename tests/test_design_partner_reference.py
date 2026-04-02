from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_design_partner_reference_runs_end_to_end(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    source = repo_root / "examples" / "design_partner_reference"
    target = tmp_path / "design_partner_reference"
    shutil.copytree(source, target)

    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root / "src")
    subprocess.run(
        [sys.executable, str(target / "run_reference.py")], check=True, env=env
    )

    manifest = json.loads((target / "artifacts" / "release-manifest.json").read_text())
    assert manifest["signer"]["signature"]

    simulation = json.loads(
        (target / "artifacts" / "simulation-report.json").read_text()
    )
    assert simulation["changed_scenarios"] >= 1

    promotion = json.loads(
        (target / "artifacts" / "promotion-validation.json").read_text()
    )
    assert promotion["promotion_validation"]["valid"] is True
    assert promotion["signature_verification"]["valid"] is True

    evaluations = json.loads(
        (target / "artifacts" / "evaluation-results.json").read_text()
    )
    assert len(evaluations) == 3

    audit = json.loads(
        (target / "artifacts" / "audit-chain-verification.json").read_text()
    )
    assert audit["valid"] is True

    review_dir = target / "artifacts" / "review_packages"
    assert len(list(review_dir.glob("*.json"))) == 3
