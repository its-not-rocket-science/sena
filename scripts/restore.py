from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from sena.audit.chain import verify_audit_chain


def run_restore(manifest_path: Path, restore_db: Path, restore_audit_dir: Path, verify: bool = True) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    source_db = Path(manifest["sqlite_db"])
    restore_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_db, restore_db)

    restore_audit_dir.mkdir(parents=True, exist_ok=True)
    restored_files = []
    for path_str in manifest.get("audit_files", []):
        src = Path(path_str)
        dst = restore_audit_dir / src.name
        shutil.copy2(src, dst)
        restored_files.append(str(dst))

    verify_result = None
    if verify:
        primary = sorted(restore_audit_dir.glob("*.jsonl"))
        if primary:
            verify_result = verify_audit_chain(str(primary[0]))
            if not verify_result.get("valid", False):
                raise RuntimeError("restore verification failed")

    return {
        "restored_db": str(restore_db),
        "restored_audit_files": restored_files,
        "verify": verify_result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore SENA SQLite + audit artifacts from backup manifest")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--restore-db", required=True, type=Path)
    parser.add_argument("--restore-audit-dir", required=True, type=Path)
    parser.add_argument("--no-verify", action="store_true")
    args = parser.parse_args()

    restored = run_restore(
        manifest_path=args.manifest,
        restore_db=args.restore_db,
        restore_audit_dir=args.restore_audit_dir,
        verify=not args.no_verify,
    )
    print(json.dumps(restored, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
