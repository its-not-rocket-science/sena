from __future__ import annotations

import json

from sena.policy.disaster_recovery import (
    DisasterRecoveryError,
    build_restore_arg_parser,
    restore_policy_registry_backup,
)


def main() -> None:
    parser = build_restore_arg_parser()
    args = parser.parse_args()
    try:
        result = restore_policy_registry_backup(
            backup_db_path=args.backup_db,
            restore_db_path=args.restore_db,
            backup_manifest_path=args.backup_manifest,
            backup_audit_path=args.backup_audit,
            restore_audit_path=args.restore_audit,
            policy_dir=args.policy_dir,
            keyring_dir=args.keyring_dir,
        )
    except DisasterRecoveryError as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps({"status": "ok", "checks": result.checks}, indent=2))


if __name__ == "__main__":
    main()
