from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sena.audit.chain import verify_audit_chain
from sena.core.enums import DecisionOutcome
from sena.core.models import ActionProposal, EvaluatorConfig
from sena.engine.evaluator import PolicyEvaluator
from sena.engine.explain import format_trace
from sena.engine.simulation import SimulationScenario, simulate_bundle_impact
from sena.examples import DEFAULT_POLICY_DIR
from sena.policy.lifecycle import diff_rule_sets, validate_promotion
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
        default=DEFAULT_POLICY_DIR,
        help="Directory containing YAML policy files",
    )
    parser.add_argument(
        "--policy-bundle-name",
        default="enterprise-compliance-controls",
        help="Name for the policy bundle metadata in output",
    )
    parser.add_argument(
        "--bundle-version",
        default="2026.03",
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
    parser.add_argument(
        "--compare-policy-dir",
        type=Path,
        help="Optional second policy directory used for diff/promotion validation",
    )
    parser.add_argument(
        "--simulate-scenarios",
        type=Path,
        help="Optional JSON file containing map of simulation scenarios",
    )
    parser.add_argument(
        "--validate-promotion",
        action="store_true",
        help="When --compare-policy-dir is set, run lifecycle promotion validation",
    )
    parser.add_argument(
        "--verify-audit-chain",
        type=Path,
        help="Verify tamper-evident audit chain JSONL and exit",
    )
    args = parser.parse_args()

    if args.verify_audit_chain:
        print(json.dumps(verify_audit_chain(str(args.verify_audit_chain)), indent=2))
        return

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

    if args.compare_policy_dir:
        compare_rules, compare_meta = load_policy_bundle(args.compare_policy_dir)
        print(
            json.dumps(diff_rule_sets(rules, compare_rules).__dict__, indent=2),
            file=sys.stderr,
        )
        if args.validate_promotion:
            print(
                json.dumps(
                    validate_promotion(metadata.lifecycle, compare_meta.lifecycle, rules, compare_rules).__dict__,
                    indent=2,
                ),
                file=sys.stderr,
            )
        if args.simulate_scenarios:
            scenarios_payload = json.loads(args.simulate_scenarios.read_text())
            scenarios = {
                scenario_id: SimulationScenario(
                    action_type=item["action_type"],
                    request_id=item.get("request_id"),
                    actor_id=item.get("actor_id"),
                    attributes=item.get("attributes", {}),
                    facts=item.get("facts", {}),
                )
                for scenario_id, item in scenarios_payload.items()
            }
            print(
                json.dumps(
                    simulate_bundle_impact(
                        scenarios, rules, compare_rules, metadata, compare_meta
                    ),
                    indent=2,
                ),
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
