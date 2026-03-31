from __future__ import annotations

import argparse
import json
from pathlib import Path

from sena.core.models import ActionProposal
from sena.engine.evaluator import PolicyEvaluator
from sena.engine.explain import format_trace
from sena.policy.parser import load_policies_from_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="SENA compliance policy evaluator")
    parser.add_argument("scenario", type=Path, help="Path to JSON scenario file")
    parser.add_argument(
        "--policy-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "examples" / "policies",
        help="Directory containing YAML policy files",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output")
    args = parser.parse_args()

    payload = json.loads(args.scenario.read_text())
    proposal = ActionProposal(
        action_type=payload["action_type"],
        request_id=payload.get("request_id"),
        actor_id=payload.get("actor_id"),
        attributes=payload.get("attributes", {}),
    )
    facts = payload.get("facts", {})

    evaluator = PolicyEvaluator(load_policies_from_dir(args.policy_dir))
    trace = evaluator.evaluate(proposal, facts)

    if args.json:
        print(json.dumps(trace.to_dict(), indent=2, default=str))
    else:
        print(format_trace(trace))


if __name__ == "__main__":
    main()
