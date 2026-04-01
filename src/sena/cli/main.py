from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

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

TEMPLATES_ROOT = Path(__file__).resolve().parent.parent / "examples" / "policy_templates"


def parse_default_decision(raw: str) -> DecisionOutcome:
    if raw == "ESCALATE":
        return DecisionOutcome.ESCALATE_FOR_HUMAN_REVIEW
    return DecisionOutcome(raw)


def _format_error(prefix: str, exc: Exception) -> str:
    detail = str(exc).strip() or exc.__class__.__name__
    return f"{prefix}:\n  - {detail}"


def _load_json_file(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(_format_error(f"Failed to load {label} JSON from {path}", exc)) from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"Failed to load {label} JSON from {path}:\n  - Expected a JSON object")
    return payload


def _run_evaluate(args: argparse.Namespace) -> None:
    if args.verify_audit_chain:
        print(json.dumps(verify_audit_chain(str(args.verify_audit_chain)), indent=2))
        return

    payload = _load_json_file(args.scenario, "scenario")

    try:
        rules, metadata = load_policy_bundle(
            args.policy_dir,
            bundle_name=args.policy_bundle_name,
            version=args.bundle_version,
        )
    except PolicyParseError as exc:
        raise SystemExit(_format_error("Failed to load policy bundle", exc)) from exc

    try:
        uncovered = validate_policy_coverage(
            rules,
            required_action_types=args.require_action_type,
            explicitly_allowed_action_types=args.explicitly_allowed_action_type,
            strict=args.coverage_strict,
        )
    except PolicyValidationError as exc:
        raise SystemExit(_format_error("Policy coverage validation failed", exc)) from exc
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
            scenarios_payload = _load_json_file(args.simulate_scenarios, "simulation scenarios")
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
        actor_role=payload.get("actor_role"),
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


def _run_policy_init(args: argparse.Namespace) -> None:
    destination = args.path
    destination.mkdir(parents=True, exist_ok=True)
    for template in sorted(TEMPLATES_ROOT.rglob("*")):
        if template.name == "__init__.py" or not template.is_file():
            continue
        relative = template.relative_to(TEMPLATES_ROOT)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not args.force:
            raise SystemExit(
                f"Refusing to overwrite {target}. Use --force to replace existing files."
            )
        target.write_text(template.read_text())
    print(f"Initialized policy template bundle at: {destination}")


def _run_policy_validate(args: argparse.Namespace) -> None:
    try:
        rules, metadata = load_policy_bundle(args.policy_dir)
        uncovered = validate_policy_coverage(
            rules,
            required_action_types=args.require_action_type,
            explicitly_allowed_action_types=args.explicitly_allowed_action_type,
            strict=args.strict,
        )
    except (PolicyParseError, PolicyValidationError) as exc:
        raise SystemExit(_format_error("Policy validation failed", exc)) from exc

    result = {
        "status": "ok",
        "bundle_name": metadata.bundle_name,
        "version": metadata.version,
        "rule_count": len(rules),
        "coverage_missing": uncovered,
    }
    print(json.dumps(result, indent=2))


def _run_policy_test(args: argparse.Namespace) -> None:
    try:
        rules, metadata = load_policy_bundle(args.policy_dir)
    except PolicyParseError as exc:
        raise SystemExit(_format_error("Policy test setup failed", exc)) from exc

    test_payload = _load_json_file(args.test_file, "policy test")
    cases = test_payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise SystemExit("Policy test file requires non-empty 'cases' list")

    evaluator = PolicyEvaluator(rules, policy_bundle=metadata)

    failures: list[dict[str, str]] = []
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            raise SystemExit(f"Policy test case at index {index} must be an object")

        name = str(case.get("name") or f"case_{index}")
        proposal_data = case.get("proposal")
        expected = case.get("expected_outcome")
        if not isinstance(proposal_data, dict) or not isinstance(expected, str):
            raise SystemExit(
                f"Policy test case '{name}' must include 'proposal' object and 'expected_outcome'"
            )

        proposal = ActionProposal(
            action_type=proposal_data["action_type"],
            request_id=proposal_data.get("request_id"),
            actor_id=proposal_data.get("actor_id"),
            actor_role=proposal_data.get("actor_role"),
            attributes=proposal_data.get("attributes", {}),
        )
        facts = case.get("facts", {})
        trace = evaluator.evaluate(proposal, facts)
        if trace.outcome.value != expected:
            failures.append(
                {
                    "name": name,
                    "expected": expected,
                    "actual": trace.outcome.value,
                    "summary": trace.summary,
                }
            )

    report = {
        "cases": len(cases),
        "failures": len(failures),
        "passed": len(cases) - len(failures),
        "results": failures,
    }
    print(json.dumps(report, indent=2))
    if failures:
        raise SystemExit("Policy tests failed")


def _build_evaluate_parser() -> argparse.ArgumentParser:
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
    return parser


def _build_policy_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SENA policy authoring commands")
    sub = parser.add_subparsers(dest="policy_command", required=True)

    init_parser = sub.add_parser("init", help="Initialize a policy bundle from templates")
    init_parser.add_argument("path", type=Path, help="Destination directory for policy files")
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    init_parser.set_defaults(handler=_run_policy_init)

    validate_parser = sub.add_parser("validate", help="Validate policy syntax and coverage")
    validate_parser.add_argument("--policy-dir", type=Path, required=True, help="Policy directory")
    validate_parser.add_argument("--require-action-type", action="append", default=[])
    validate_parser.add_argument("--explicitly-allowed-action-type", action="append", default=[])
    validate_parser.add_argument("--strict", action="store_true", help="Fail on missing coverage")
    validate_parser.set_defaults(handler=_run_policy_validate)

    test_parser = sub.add_parser("test", help="Run behavior tests against a policy bundle")
    test_parser.add_argument("--policy-dir", type=Path, required=True, help="Policy directory")
    test_parser.add_argument("--test-file", type=Path, required=True, help="JSON file with policy cases")
    test_parser.set_defaults(handler=_run_policy_test)

    return parser


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "policy":
        parser = _build_policy_parser()
        args = parser.parse_args(sys.argv[2:])
        args.handler(args)
        return

    parser = _build_evaluate_parser()
    args = parser.parse_args()
    _run_evaluate(args)


if __name__ == "__main__":
    main()
