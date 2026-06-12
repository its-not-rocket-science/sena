from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _run_command(cmd: list[str], env: dict[str, str]) -> tuple[int, str, str]:
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return result.returncode, result.stdout, result.stderr


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run or dry-run a policy registry backup/restore verification drill"
    )
    parser.add_argument("--sqlite-path", type=Path, required=True)
    parser.add_argument("--audit-chain", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--policy-dir", type=Path)
    parser.add_argument("--keyring-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _command_payload(args: argparse.Namespace) -> dict[str, Any]:
    backup_db = args.work_dir / "registry.backup.db"
    restore_db = args.work_dir / "registry.restored.db"
    restored_audit = args.work_dir / "restored.audit.jsonl"

    backup_cmd = [
        sys.executable,
        "-m",
        "sena.cli.main",
        "registry",
        "--sqlite-path",
        str(args.sqlite_path),
        "backup",
        "--output-db",
        str(backup_db),
        "--audit-chain",
        str(args.audit_chain),
    ]

    restore_cmd = [
        sys.executable,
        "-m",
        "sena.cli.main",
        "registry",
        "--sqlite-path",
        str(restore_db),
        "restore",
        "--backup-db",
        str(backup_db),
        "--backup-manifest",
        str(backup_db.with_suffix(".db.manifest.json")),
        "--backup-audit",
        str(backup_db.with_suffix(".db.audit.jsonl")),
        "--restore-db",
        str(restore_db),
        "--restore-audit",
        str(restored_audit),
    ]
    if args.policy_dir:
        restore_cmd.extend(["--policy-dir", str(args.policy_dir)])
    if args.keyring_dir:
        restore_cmd.extend(["--keyring-dir", str(args.keyring_dir)])

    verify_cmd = [
        sys.executable,
        "-m",
        "sena.cli.main",
        "registry",
        "--sqlite-path",
        str(restore_db),
        "verify",
        "--audit-chain",
        str(restored_audit),
    ]
    if args.policy_dir:
        verify_cmd.extend(["--policy-dir", str(args.policy_dir)])
    if args.keyring_dir:
        verify_cmd.extend(["--keyring-dir", str(args.keyring_dir)])

    return {
        "backup_db": backup_db,
        "restore_db": restore_db,
        "restored_audit": restored_audit,
        "commands": [backup_cmd, restore_cmd, verify_cmd],
    }


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    payload = _command_payload(args)
    commands: list[list[str]] = payload["commands"]

    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "dry_run",
                    "work_dir": str(args.work_dir),
                    "commands": commands,
                },
                indent=2,
            )
        )
        return

    args.work_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = f"src:{env.get('PYTHONPATH', '')}".rstrip(":")

    executed: list[dict[str, Any]] = []
    for command in commands:
        code, stdout, stderr = _run_command(command, env)
        executed.append(
            {
                "command": command,
                "exit_code": code,
                "stdout": stdout,
                "stderr": stderr,
            }
        )
        if code != 0:
            print(json.dumps({"status": "failed", "steps": executed}, indent=2))
            raise SystemExit(code)

    print(json.dumps({"status": "ok", "steps": executed}, indent=2))


if __name__ == "__main__":
    main()
