from __future__ import annotations

import argparse
import json

from sena.policy.store import SQLitePolicyBundleRepository


def main() -> None:
    parser = argparse.ArgumentParser(description="Upgrade and inspect policy registry schema migrations")
    parser.add_argument("--sqlite-path", required=True, help="Path to SQLite DB file")
    parser.add_argument("--dry-run", action="store_true", help="Plan migrations without applying")
    parser.add_argument("--target-version", type=int, help="Optional target migration version")
    parser.add_argument("--inspect-only", action="store_true", help="Only inspect migration status")
    args = parser.parse_args()

    repo = SQLitePolicyBundleRepository(args.sqlite_path)
    if args.inspect_only:
        print(json.dumps(repo.inspect_schema(), indent=2))
        return

    result = repo.upgrade_schema(dry_run=args.dry_run, target_version=args.target_version)
    print(
        json.dumps(
            {
                "status": "dry-run" if result.dry_run else "ok",
                "initial_version": result.initial_version,
                "target_version": result.target_version,
                "applied_versions": result.applied_versions,
                "pending_versions": result.pending_versions,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
