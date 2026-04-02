from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run_cmd(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = f"src:{env.get('PYTHONPATH', '')}".rstrip(":")
    return subprocess.run(args, capture_output=True, text=True, env=env, check=True)


def _relative_file_set(root: Path) -> set[str]:
    return {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}


def test_generate_evidence_pack_script_and_deterministic_structure(
    tmp_path: Path,
) -> None:
    out1 = tmp_path / "pack-1"
    out2 = tmp_path / "pack-2"

    _run_cmd(
        [
            sys.executable,
            "scripts/generate_evidence_pack.py",
            "--output-dir",
            str(out1),
            "--clean",
        ]
    )
    _run_cmd(
        [
            sys.executable,
            "scripts/generate_evidence_pack.py",
            "--output-dir",
            str(out2),
            "--clean",
        ]
    )

    assert _relative_file_set(out1) == _relative_file_set(out2)

    promotion = json.loads(
        (out1 / "artifacts" / "promotion_validation.json").read_text()
    )
    assert promotion["promotion_validation"]["valid"] is True

    audit = json.loads((out1 / "artifacts" / "audit_verification.json").read_text())
    assert audit["valid"] is True

    summary = (out1 / "SUMMARY.md").read_text()
    assert "simulation_summary.json" in summary


def test_cli_evidence_pack_command(tmp_path: Path) -> None:
    out = tmp_path / "pack"
    zip_path = tmp_path / "pack.zip"
    result = _run_cmd(
        [
            sys.executable,
            "-m",
            "sena.cli.main",
            "evidence-pack",
            "--output-dir",
            str(out),
            "--output-zip",
            str(zip_path),
            "--clean",
        ]
    )
    payload = json.loads(result.stdout)
    assert Path(payload["output_dir"]) == out
    assert zip_path.exists()
    assert (out / "artifacts" / "integration_examples_index.json").exists()
