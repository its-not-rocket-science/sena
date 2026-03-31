from __future__ import annotations

import argparse
import json
from pathlib import Path

from sena.core.models import ActionProposal
from sena.engine.evaluator import PolicyEvaluator
from sena.engine.explain import format_trace
from sena.policy.parser import PolicyParseError, load_policy_bundle


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "SENA deterministic policy evaluator for enterprise compliance "
            "and approval workflows"
        )
    )
    parser.add_argument("scenario", type=Path, help="Path to JSON scenario file")
    parser.add_argument(
        "--policy-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "examples" / "policies",
        help="Directory containing YAML policy files",
    )
    parser.add_argument(
        "--policy-bundle-name",
        default="default-bundle",
        help="Name for the policy bundle metadata in output",
    )
    parser.add_argument(
        "--bundle-version",
        default="0.1.0-alpha",
        help="Version string for the policy bundle metadata in output",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output")
    args = parser.parse_args()

    try:
        payload = json.loads(args.scenario.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Failed to load scenario JSON: {exc}") from exc

    try:
        rules, metadata = load_policy_bundle(
            args.policy_dir,
            bundle_name=args.policy_bundle_name,
            version=args.bundle_version,
        )
    except PolicyParseError as exc:
        raise SystemExit(f"Failed to load policy bundle: {exc}") from exc

    proposal = ActionProposal(
        action_type=payload["action_type"],
        request_id=payload.get("request_id"),
        actor_id=payload.get("actor_id"),
        attributes=payload.get("attributes", {}),
    )
    facts = payload.get("facts", {})

    evaluator = PolicyEvaluator(rules, policy_bundle=metadata)
    trace = evaluator.evaluate(proposal, facts)

    if args.json:
        print(json.dumps(trace.to_dict(), indent=2, default=str))
    else:
        print(format_trace(trace))


if __name__ == "__main__":
    main()
