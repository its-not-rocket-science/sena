from __future__ import annotations

import json

from sena.policy.disaster_recovery import build_backup_arg_parser, create_policy_registry_backup


def main() -> None:
    parser = build_backup_arg_parser()
    args = parser.parse_args()
    artifacts = create_policy_registry_backup(
        sqlite_path=args.sqlite_path,
        output_db_path=args.output_db,
        audit_chain_path=args.audit_chain,
        output_manifest_path=args.output_manifest,
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "backup_db_path": str(artifacts.backup_db_path),
                "backup_manifest_path": str(artifacts.backup_manifest_path),
                "backup_audit_path": str(artifacts.backup_audit_path) if artifacts.backup_audit_path else None,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
