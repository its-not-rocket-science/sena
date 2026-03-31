from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sena.core.enums import DecisionOutcome
from sena.core.models import ActionProposal, EvaluatorConfig
from sena.engine.evaluator import PolicyEvaluator
from sena.engine.explain import format_trace
from sena.policy.parser import PolicyParseError, load_policy_bundle
from sena.policy.validation import PolicyValidationError, validate_policy_coverage


def parse_default_decision(raw: str) -> DecisionOutcome:
    if raw == "ESCALATE":
        return DecisionOutcome.ESCALATE_FOR_HUMAN_REVIEW
    return DecisionOutcome(raw)


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
    parser.add_argument(
        "--default-decision",
        choices=[outcome.value for outcome in DecisionOutcome] + ["ESCALATE"],
        default=DecisionOutcome.APPROVED.value,
        help="Fallback decision when no rules match",
    )
    parser.add_argument(
        "--strict-require-allow",
        action="store_true",
        help="Require at least one matching ALLOW rule",
    )
    parser.add_argument(
        "--require-action-type",
        action="append",
        default=[],
        help="Action type that must be covered by at least one policy rule",
    )
    parser.add_argument(
        "--explicitly-allowed-action-type",
        action="append",
        default=[],
        help="Action type intentionally left without explicit policy rule",
    )
    parser.add_argument(
        "--coverage-strict",
        action="store_true",
        help="Fail if required action types are not covered",
    )
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

    try:
        uncovered = validate_policy_coverage(
            rules,
            required_action_types=args.require_action_type,
            explicitly_allowed_action_types=args.explicitly_allowed_action_type,
            strict=args.coverage_strict,
        )
    except PolicyValidationError as exc:
        raise SystemExit(f"Policy coverage validation failed: {exc}") from exc
    if uncovered:
        print(
            f"Policy coverage warning: missing required coverage for action_type(s): {sorted(uncovered)}",
            file=sys.stderr,
        )

    proposal = ActionProposal(
        action_type=payload["action_type"],
        request_id=payload.get("request_id"),
        actor_id=payload.get("actor_id"),
        attributes=payload.get("attributes", {}),
    )
    facts = payload.get("facts", {})

    evaluator = PolicyEvaluator(
        rules,
        policy_bundle=metadata,
        config=EvaluatorConfig(
            default_decision=parse_default_decision(args.default_decision),
            require_allow_match=args.strict_require_allow,
        ),
    )
    trace = evaluator.evaluate(proposal, facts)

    if args.json:
        print(json.dumps(trace.to_dict(), indent=2, default=str))
    else:
        print(format_trace(trace))


if __name__ == "__main__":
    main()
