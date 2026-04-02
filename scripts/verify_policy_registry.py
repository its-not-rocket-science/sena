from __future__ import annotations

import json

from sena.policy.disaster_recovery import build_verify_arg_parser, verify_policy_registry_snapshot


def main() -> None:
    parser = build_verify_arg_parser()
    args = parser.parse_args()
    result = verify_policy_registry_snapshot(
        sqlite_path=args.sqlite_path,
        audit_chain_path=args.audit_chain,
        policy_dir=args.policy_dir,
        keyring_dir=args.keyring_dir,
        active_only=args.active_only,
    )
    payload = {"status": "ok" if result.valid else "failed", "checks": result.checks, "errors": result.errors}
    print(json.dumps(payload, indent=2))
    if not result.valid:
        raise SystemExit("registry verification failed")


if __name__ == "__main__":
    main()
