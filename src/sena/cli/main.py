from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sena import __version__ as SENA_VERSION
from sena.audit.chain import locate_decision_in_audit, summarize_audit_chain, verify_audit_chain
from sena.api.config import load_settings_from_env
from sena.api.production_check import run_production_readiness_check
from sena.core.enums import DecisionOutcome
from sena.core.models import ActionProposal, EvaluatorConfig
from sena.engine.evaluator import PolicyEvaluator
from sena.engine.explain import format_trace
from sena.engine.review_package import build_decision_review_package
from sena.engine.simulation import SimulationScenario, simulate_bundle_impact
from sena.examples import DEFAULT_POLICY_DIR
from sena.policy.lifecycle import diff_rule_sets, validate_promotion
from sena.policy.parser import PolicyParseError, load_policy_bundle
from sena.policy.schema_evolution import (
    CURRENT_BUNDLE_SCHEMA_VERSION,
    BundleMigrationResult,
    VersionRange,
    evaluate_bundle_compatibility,
    format_migration_report,
    migrate_bundle,
)
from sena.policy.release_signing import (
    BundleReleaseManifest,
    generate_release_manifest,
    sign_release_manifest,
    verify_release_manifest,
    write_release_manifest,
)
from sena.policy.disaster_recovery import (
    DisasterRecoveryError,
    create_policy_registry_backup,
    restore_policy_registry_backup,
)
from sena.policy.store import SQLitePolicyBundleRepository
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

    if args.review_package:
        print(json.dumps(build_decision_review_package(trace), indent=2, default=str))
    elif args.json:
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
        target.write_bytes(template.read_bytes())
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


def _run_policy_schema_version(args: argparse.Namespace) -> None:
    _, metadata = load_policy_bundle(args.policy_dir)
    compatibility = evaluate_bundle_compatibility(schema_version=metadata.schema_version)
    print(
        json.dumps(
            {
                "bundle_name": metadata.bundle_name,
                "version": metadata.version,
                "schema_version": metadata.schema_version,
                "current_supported_schema_version": CURRENT_BUNDLE_SCHEMA_VERSION,
                "warnings": compatibility.warnings,
            },
            indent=2,
        )
    )


def _run_policy_migrate(args: argparse.Namespace) -> None:
    result: BundleMigrationResult = migrate_bundle(
        args.policy_dir,
        target_schema_version=args.target_schema_version,
        dry_run=args.dry_run,
    )
    print(json.dumps(format_migration_report(result), indent=2))


def _run_policy_verify_compatibility(args: argparse.Namespace) -> None:
    _, metadata = load_policy_bundle(args.policy_dir)
    compatibility = None
    if args.min_evaluator_version or args.max_evaluator_version:
        compatibility = VersionRange(
            min_inclusive=args.min_evaluator_version,
            max_inclusive=args.max_evaluator_version,
        )
    report = evaluate_bundle_compatibility(
        schema_version=metadata.schema_version,
        runtime_version=args.runtime_version,
        compatibility=compatibility,
    )
    print(
        json.dumps(
            {
                "compatible": report.compatible,
                "runtime_version": args.runtime_version,
                "schema_version": metadata.schema_version,
                "errors": report.errors,
                "warnings": report.warnings,
            },
            indent=2,
        )
    )
    if not report.compatible:
        raise SystemExit("Bundle is incompatible with runtime")




def _registry_repo(sqlite_path: Path) -> SQLitePolicyBundleRepository:
    repo = SQLitePolicyBundleRepository(str(sqlite_path))
    repo.initialize()
    return repo


def _resolve_signature_verification(
    *,
    policy_dir: Path,
    manifest_path: Path | None,
    keyring_dir: Path | None,
    strict: bool,
) -> tuple[bool, list[str], str | None]:
    path = manifest_path or (policy_dir / "release-manifest.json")
    if not path.exists():
        if strict:
            return False, [f"release manifest not found: {path}"], str(path)
        return True, [], None
    result = verify_release_manifest(
        policy_dir,
        manifest_path=path,
        keyring_dir=keyring_dir,
        strict=strict,
    )
    return result.valid, result.errors, str(path)


def _run_registry_register(args: argparse.Namespace) -> None:
    repo = _registry_repo(args.sqlite_path)
    rules, metadata = load_policy_bundle(args.policy_dir, bundle_name=args.bundle_name, version=args.bundle_version)
    metadata.lifecycle = args.lifecycle
    signature_ok, signature_errors, manifest_path = _resolve_signature_verification(
        policy_dir=args.policy_dir,
        manifest_path=args.manifest_path,
        keyring_dir=args.keyring_dir,
        strict=args.signature_strict,
    )
    if args.signature_strict and not signature_ok:
        raise SystemExit(f"Bundle signature verification failed: {', '.join(signature_errors)}")
    bundle_id = repo.register_bundle(
        metadata,
        rules,
        created_by=args.created_by,
        creation_reason=args.creation_reason,
        source_bundle_id=args.source_bundle_id,
        compatibility_notes=args.compatibility_notes,
        release_notes=args.release_notes,
        migration_notes=args.migration_notes,
        release_manifest_path=manifest_path,
        signature_verification_strict=args.signature_strict,
        signature_verified=signature_ok,
        signature_error="; ".join(signature_errors) if signature_errors else None,
    )
    print(
        json.dumps(
            {
                "bundle_id": bundle_id,
                "bundle_name": metadata.bundle_name,
                "version": metadata.version,
                "signature": {"verified": signature_ok, "errors": signature_errors},
            },
            indent=2,
        )
    )


def _run_registry_history(args: argparse.Namespace) -> None:
    repo = _registry_repo(args.sqlite_path)
    print(json.dumps({"bundle_name": args.bundle_name, "history": repo.get_history(args.bundle_name)}, indent=2))


def _run_registry_diff(args: argparse.Namespace) -> None:
    repo = _registry_repo(args.sqlite_path)
    current = repo.get_bundle(args.current_bundle_id)
    target = repo.get_bundle(args.target_bundle_id)
    if current is None or target is None:
        raise SystemExit("Bundle id not found")
    print(json.dumps(diff_rule_sets(current.rules, target.rules).__dict__, indent=2))


def _run_registry_validate(args: argparse.Namespace) -> None:
    repo = _registry_repo(args.sqlite_path)
    bundle = repo.get_bundle(args.bundle_id)
    if bundle is None:
        raise SystemExit("Bundle id not found")
    source_rules = bundle.rules
    if args.target_lifecycle == "active":
        active = repo.get_active_bundle(bundle.metadata.bundle_name)
        source_rules = active.rules if active else []
    print(
        json.dumps(
            validate_promotion(
                bundle.metadata.lifecycle,
                args.target_lifecycle,
                source_rules,
                bundle.rules,
                validation_artifact=args.validation_artifact,
                signature_verified=bundle.signature_verified,
                signature_verification_strict=bundle.signature_verification_strict,
            ).__dict__,
            indent=2,
        )
    )


def _run_release_generate(args: argparse.Namespace) -> None:
    manifest = generate_release_manifest(
        args.policy_dir,
        bundle_name=args.bundle_name,
        version=args.bundle_version,
        key_id=args.key_id,
        signer_name=args.signer_name,
        compatibility_notes=args.compatibility_notes,
        migration_notes=args.migration_notes,
    )
    write_release_manifest(manifest, args.output)
    print(json.dumps({"status": "ok", "manifest_path": str(args.output)}, indent=2))


def _run_release_sign(args: argparse.Namespace) -> None:
    manifest = BundleReleaseManifest.model_validate(json.loads(args.manifest_path.read_text()))
    signed = sign_release_manifest(manifest, key_path=args.key_file)
    write_release_manifest(signed, args.output or args.manifest_path)
    print(json.dumps({"status": "ok", "manifest_path": str(args.output or args.manifest_path)}, indent=2))


def _run_release_verify(args: argparse.Namespace) -> None:
    result = verify_release_manifest(
        args.policy_dir,
        manifest_path=args.manifest_path,
        keyring_dir=args.keyring_dir,
        strict=args.strict,
    )
    print(json.dumps({"valid": result.valid, "errors": result.errors}, indent=2))
    if not result.valid:
        raise SystemExit("Manifest verification failed")


def _run_registry_promote(args: argparse.Namespace) -> None:
    repo = _registry_repo(args.sqlite_path)
    simulation_scenarios: list[dict[str, Any]] = []
    if args.simulation_scenarios:
        simulation_payload = _load_json_file(args.simulation_scenarios, "simulation scenarios")
        simulation_scenarios = [
            {"scenario_id": sid, **scenario} for sid, scenario in sorted(simulation_payload.items())
        ]
    thresholds = {
        "max_changed_outcomes": args.max_changed_outcomes,
        "max_block_to_approve_regressions": args.max_block_to_approve_regressions,
        "max_missing_scenario_coverage": args.max_missing_scenario_coverage,
        "required_risk_categories": args.required_risk_category or [],
        "max_changed_risk_categories": {},
    }
    for item in args.max_changed_risk_category or []:
        risk, _, raw_max = item.partition("=")
        if not risk or not raw_max:
            raise SystemExit("Invalid --max-changed-risk-category format. Use risk=max_changed_count")
        thresholds["max_changed_risk_categories"][risk] = int(raw_max)
    repo.transition_bundle(
        args.bundle_id,
        args.target_lifecycle,
        promoted_by=args.promoted_by,
        promotion_reason=args.promotion_reason,
        validation_artifact=args.validation_artifact,
        policy_diff_summary=json.dumps({"cli_only": True}, sort_keys=True),
        evidence_json=json.dumps(
            {
                "simulation_scenarios_count": len(simulation_scenarios),
                "thresholds": thresholds,
                "break_glass_reason": args.break_glass_reason,
            },
            sort_keys=True,
        ),
        break_glass=args.break_glass,
        audit_marker="break_glass_promotion" if args.break_glass else "promotion",
        action="promote_break_glass" if args.break_glass else "promote",
    )
    print(json.dumps({"status": "ok"}, indent=2))


def _run_registry_rollback(args: argparse.Namespace) -> None:
    repo = _registry_repo(args.sqlite_path)
    repo.rollback_bundle(
        args.bundle_name,
        args.to_bundle_id,
        promoted_by=args.promoted_by,
        promotion_reason=args.promotion_reason,
        validation_artifact=args.validation_artifact,
    )
    print(json.dumps({"status": "ok"}, indent=2))


def _run_registry_fetch_active(args: argparse.Namespace) -> None:
    repo = _registry_repo(args.sqlite_path)
    bundle = repo.get_active_bundle(args.bundle_name)
    if bundle is None:
        raise SystemExit("No active bundle")
    print(json.dumps({"bundle_id": bundle.id, "bundle_name": bundle.metadata.bundle_name, "version": bundle.metadata.version}, indent=2))


def _run_registry_fetch(args: argparse.Namespace) -> None:
    repo = _registry_repo(args.sqlite_path)
    bundle = repo.get_bundle(args.bundle_id) if args.bundle_id else repo.get_bundle_by_version(args.bundle_name, args.version)
    if bundle is None:
        raise SystemExit("Bundle not found")
    print(json.dumps({"bundle_id": bundle.id, "bundle_name": bundle.metadata.bundle_name, "version": bundle.metadata.version, "lifecycle": bundle.metadata.lifecycle}, indent=2))


def _run_registry_backup(args: argparse.Namespace) -> None:
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


def _run_registry_restore(args: argparse.Namespace) -> None:
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


def _run_audit_verify(args: argparse.Namespace) -> None:
    result = verify_audit_chain(str(args.audit_path))
    print(json.dumps(result, indent=2))
    if not result.get("valid", False):
        raise SystemExit("Audit verification failed")


def _run_audit_summarize(args: argparse.Namespace) -> None:
    print(json.dumps(summarize_audit_chain(str(args.audit_path)), indent=2))


def _run_audit_locate_decision(args: argparse.Namespace) -> None:
    result = locate_decision_in_audit(str(args.audit_path), args.decision_id)
    print(json.dumps(result, indent=2))
    if not result.get("found", False):
        raise SystemExit("Decision not found in audit chain")


def _run_production_check(args: argparse.Namespace) -> None:
    settings = load_settings_from_env()
    report = run_production_readiness_check(settings)

    if args.format in {"text", "both"}:
        status = "PASS" if report["ok"] else "FAIL"
        print(f"Production readiness check: {status}")
        for check in report["checks"]:
            marker = "✓" if check["status"] == "pass" else "✗"
            print(f"- {marker} {check['name']}")
            for detail in check["details"]:
                print(f"    • {detail}")
    if args.format in {"json", "both"}:
        print(json.dumps(report, indent=2))

    if not report["ok"]:
        raise SystemExit(1)


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
        "--review-package",
        action="store_true",
        help="Output durable decision review package JSON artefact",
    )
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

    schema_parser = sub.add_parser("schema-version", help="Inspect bundle schema version")
    schema_parser.add_argument("--policy-dir", type=Path, required=True, help="Policy directory")
    schema_parser.set_defaults(handler=_run_policy_schema_version)

    migrate_parser = sub.add_parser("migrate", help="Migrate bundle manifest/rules to a target schema")
    migrate_parser.add_argument("--policy-dir", type=Path, required=True, help="Policy directory")
    migrate_parser.add_argument("--target-schema-version", default=CURRENT_BUNDLE_SCHEMA_VERSION)
    migrate_parser.add_argument("--dry-run", action="store_true", help="Preview migration changes only")
    migrate_parser.set_defaults(handler=_run_policy_migrate)

    compatibility_parser = sub.add_parser("verify-compatibility", help="Verify runtime compatibility")
    compatibility_parser.add_argument("--policy-dir", type=Path, required=True, help="Policy directory")
    compatibility_parser.add_argument("--runtime-version", default=SENA_VERSION, help="Evaluator runtime version")
    compatibility_parser.add_argument("--min-evaluator-version")
    compatibility_parser.add_argument("--max-evaluator-version")
    compatibility_parser.set_defaults(handler=_run_policy_verify_compatibility)

    return parser




def _build_registry_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SENA sqlite policy registry commands")
    parser.add_argument("--sqlite-path", type=Path, required=True)
    sub = parser.add_subparsers(dest="registry_command", required=True)

    register = sub.add_parser("register")
    register.add_argument("--policy-dir", type=Path, required=True)
    register.add_argument("--bundle-name", required=True)
    register.add_argument("--bundle-version", required=True)
    register.add_argument("--lifecycle", default="draft", choices=["draft", "candidate", "active", "deprecated"])
    register.add_argument("--created-by", default="system")
    register.add_argument("--creation-reason")
    register.add_argument("--source-bundle-id", type=int)
    register.add_argument("--compatibility-notes")
    register.add_argument("--release-notes")
    register.add_argument("--migration-notes")
    register.add_argument("--manifest-path", type=Path)
    register.add_argument("--keyring-dir", type=Path)
    register.add_argument("--signature-strict", action="store_true")
    register.set_defaults(handler=_run_registry_register)

    history = sub.add_parser("inspect-history")
    history.add_argument("--bundle-name", required=True)
    history.set_defaults(handler=_run_registry_history)

    diff = sub.add_parser("diff")
    diff.add_argument("--current-bundle-id", type=int, required=True)
    diff.add_argument("--target-bundle-id", type=int, required=True)
    diff.set_defaults(handler=_run_registry_diff)

    validate = sub.add_parser("validate-promotion")
    validate.add_argument("--bundle-id", type=int, required=True)
    validate.add_argument("--target-lifecycle", required=True, choices=["candidate", "active", "deprecated"])
    validate.add_argument("--validation-artifact")
    validate.set_defaults(handler=_run_registry_validate)

    promote = sub.add_parser("promote")
    promote.add_argument("--bundle-id", type=int, required=True)
    promote.add_argument("--target-lifecycle", required=True, choices=["candidate", "active", "deprecated"])
    promote.add_argument("--promoted-by", required=True)
    promote.add_argument("--promotion-reason", required=True)
    promote.add_argument("--validation-artifact")
    promote.add_argument("--simulation-scenarios", type=Path)
    promote.add_argument("--max-changed-outcomes", type=int)
    promote.add_argument("--max-block-to-approve-regressions", type=int)
    promote.add_argument("--max-missing-scenario-coverage", type=int)
    promote.add_argument("--required-risk-category", action="append")
    promote.add_argument("--max-changed-risk-category", action="append")
    promote.add_argument("--break-glass", action="store_true")
    promote.add_argument("--break-glass-reason")
    promote.set_defaults(handler=_run_registry_promote)

    rollback = sub.add_parser("rollback")
    rollback.add_argument("--bundle-name", required=True)
    rollback.add_argument("--to-bundle-id", type=int, required=True)
    rollback.add_argument("--promoted-by", required=True)
    rollback.add_argument("--promotion-reason", required=True)
    rollback.add_argument("--validation-artifact", required=True)
    rollback.set_defaults(handler=_run_registry_rollback)

    active = sub.add_parser("fetch-active")
    active.add_argument("--bundle-name", required=True)
    active.set_defaults(handler=_run_registry_fetch_active)

    fetch = sub.add_parser("fetch")
    fetch.add_argument("--bundle-id", type=int)
    fetch.add_argument("--bundle-name")
    fetch.add_argument("--version")
    fetch.set_defaults(handler=_run_registry_fetch)

    backup = sub.add_parser("backup")
    backup.add_argument("--output-db", type=Path, required=True)
    backup.add_argument("--audit-chain", type=Path)
    backup.add_argument("--output-manifest", type=Path)
    backup.set_defaults(handler=_run_registry_backup)

    restore = sub.add_parser("restore")
    restore.add_argument("--backup-db", type=Path, required=True)
    restore.add_argument("--restore-db", type=Path, required=True)
    restore.add_argument("--backup-manifest", type=Path)
    restore.add_argument("--backup-audit", type=Path)
    restore.add_argument("--restore-audit", type=Path)
    restore.add_argument("--policy-dir", type=Path)
    restore.add_argument("--keyring-dir", type=Path)
    restore.set_defaults(handler=_run_registry_restore)

    return parser


def _build_release_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SENA bundle release manifest commands")
    sub = parser.add_subparsers(dest="release_command", required=True)

    generate = sub.add_parser("generate-manifest")
    generate.add_argument("--policy-dir", type=Path, required=True)
    generate.add_argument("--output", type=Path, required=True)
    generate.add_argument("--bundle-name")
    generate.add_argument("--bundle-version")
    generate.add_argument("--key-id", default="unsigned")
    generate.add_argument("--signer-name")
    generate.add_argument("--compatibility-notes")
    generate.add_argument("--migration-notes")
    generate.set_defaults(handler=_run_release_generate)

    sign = sub.add_parser("sign-manifest")
    sign.add_argument("--manifest-path", type=Path, required=True)
    sign.add_argument("--key-file", type=Path, required=True)
    sign.add_argument("--output", type=Path)
    sign.set_defaults(handler=_run_release_sign)

    verify = sub.add_parser("verify-manifest")
    verify.add_argument("--policy-dir", type=Path, required=True)
    verify.add_argument("--manifest-path", type=Path, required=True)
    verify.add_argument("--keyring-dir", type=Path)
    verify.add_argument("--strict", action="store_true")
    verify.set_defaults(handler=_run_release_verify)
    return parser


def _build_audit_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SENA audit chain operational commands")
    parser.add_argument("--audit-path", type=Path, required=True, help="Path to active JSONL audit sink")
    sub = parser.add_subparsers(dest="audit_command", required=True)

    verify = sub.add_parser("verify", help="Verify full chain integrity across rotated segments")
    verify.set_defaults(handler=_run_audit_verify)

    summarize = sub.add_parser("summarize", help="Summarize chain/manifest status")
    summarize.set_defaults(handler=_run_audit_summarize)

    locate = sub.add_parser("locate-decision", help="Locate a specific decision id within audit chain")
    locate.add_argument("decision_id")
    locate.set_defaults(handler=_run_audit_locate_decision)
    return parser


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "production-check":
        parser = argparse.ArgumentParser(description="SENA production-readiness validation")
        parser.add_argument(
            "--format",
            choices=["text", "json", "both"],
            default="both",
            help="Output format for readiness report",
        )
        args = parser.parse_args(sys.argv[2:])
        _run_production_check(args)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "policy":
        parser = _build_policy_parser()
        args = parser.parse_args(sys.argv[2:])
        args.handler(args)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "registry":
        parser = _build_registry_parser()
        args = parser.parse_args(sys.argv[2:])
        args.handler(args)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "bundle-release":
        parser = _build_release_parser()
        args = parser.parse_args(sys.argv[2:])
        args.handler(args)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "audit":
        parser = _build_audit_parser()
        args = parser.parse_args(sys.argv[2:])
        args.handler(args)
        return

    parser = _build_evaluate_parser()
    args = parser.parse_args()
    _run_evaluate(args)


if __name__ == "__main__":
    main()
