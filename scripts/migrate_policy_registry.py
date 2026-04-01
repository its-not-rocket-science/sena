from __future__ import annotations

import argparse

from sena.policy.store import SQLitePolicyBundleRepository


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply policy registry migration")
    parser.add_argument("--sqlite-path", required=True, help="Path to SQLite DB file")
    args = parser.parse_args()

    repo = SQLitePolicyBundleRepository(args.sqlite_path)
    repo.initialize()
    print(f"Applied policy registry migration to {args.sqlite_path}")


if __name__ == "__main__":
    main()
