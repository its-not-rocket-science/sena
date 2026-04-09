from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sena import __version__ as SENA_VERSION
from sena.audit.chain import (
    locate_decision_in_audit,
    summarize_audit_chain,
    verify_audit_chain,
)
from sena.audit.archive import (
    create_audit_archive,
    restore_audit_archive,
    verify_audit_archive,
)
from sena.audit.evidentiary import (
    AuditRecordVerifier,
    export_evidence_bundle,
    load_signer_from_keyring_file,
)
from sena.api.config import load_settings_from_env
from sena.api.production_check import run_production_readiness_check
from sena.core.enums import DecisionOutcome
from sena.core.models import ActionProposal, EvaluatorConfig
from sena.engine.evaluator import PolicyEvaluator
from sena.engine.replay import (
    build_drift_report,
    evaluate_replay_cases,
    load_replay_cases,
)
from sena.engine.explain import format_trace
from sena.engine.review_package import build_decision_review_package
from sena.engine.simulation import SimulationScenario, simulate_bundle_impact
from sena.evidence_pack import build_evidence_pack, stable_zip_dir
from sena.examples import DEFAULT_POLICY_DIR
from sena.policy.lifecycle import (
    PromotionGatePolicy,
    diff_rule_sets,
    evaluate_promotion_gate,
    validate_promotion,
)
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
    verify_policy_registry_snapshot,
)
from sena.policy.store import SQLitePolicyBundleRepository
from sena.policy.validation import PolicyValidationError, validate_policy_coverage
from sena.schemas import EvaluatePayload
from sena.policy.test_runner import PolicyTestRunnerError, run_policy_tests

TEMPLATES_ROOT = (
    Path(__file__).resolve().parent.parent / "examples" / "policy_templates"
)


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
        raise SystemExit(
            _format_error(f"Failed to load {label} JSON from {path}", exc)
        ) from exc
    if not isinstance(payload, dict):
        raise SystemExit(
            f"Failed to load {label} JSON from {path}:\n  - Expected a JSON object"
        )
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
        raise SystemExit(
            _format_error("Policy coverage validation failed", exc)
        ) from exc
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
                    validate_promotion(
                        metadata.lifecycle, compare_meta.lifecycle, rules, compare_rules
                    ).__dict__,
                    indent=2,
                ),
                file=sys.stderr,
            )
        if args.simulate_scenarios:
            scenarios_payload = _load_json_file(
                args.simulate_scenarios, "simulation scenarios"
            )
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

    cli_request = EvaluatePayload.model_validate(
        {
            **payload,
            "default_decision": args.default_decision,
            "strict_require_allow": args.strict_require_allow,
            "dry_run": bool(args.dry_run),
        }
    )

    proposal = cli_request.to_action_proposal(
        cli_request.request_id or payload.get("request_id") or "req-cli"
    )
    evaluator = PolicyEvaluator(
        rules,
        policy_bundle=metadata,
        config=EvaluatorConfig(
            default_decision=cli_request.to_default_decision(),
            require_allow_match=cli_request.strict_require_allow,
        ),
    )
    trace = evaluator.evaluate(proposal, cli_request.facts)

    if args.review_package:
        payload = build_decision_review_package(trace)
        if args.dry_run:
            payload["dry_run"] = True
        print(json.dumps(payload, indent=2, default=str))
    elif args.json:
        payload = trace.to_dict()
        if args.dry_run:
            payload["dry_run"] = True
        print(json.dumps(payload, indent=2, default=str))
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
    legacy_mode = bool(args.policy_dir or args.test_file)
    modern_mode = bool(args.bundle or args.tests)
    if legacy_mode and modern_mode:
        raise SystemExit(
            "Use either legacy --policy-dir/--test-file or --bundle/--tests, not both"
        )
    if legacy_mode and (not args.policy_dir or not args.test_file):
        raise SystemExit("Legacy policy test mode requires both --policy-dir and --test-file")
    if modern_mode and (not args.bundle or not args.tests):
        raise SystemExit("Policy test mode requires both --bundle and --tests")
    if not legacy_mode and not modern_mode:
        raise SystemExit("Provide --bundle and --tests")

    if args.policy_dir and args.test_file:
        # Backward-compatible legacy JSON test format.
        test_payload = _load_json_file(args.test_file, "policy test")
        cases = test_payload.get("cases")
        if not isinstance(cases, list) or not cases:
            raise SystemExit("Policy test file requires non-empty 'cases' list")
        try:
            rules, metadata = load_policy_bundle(args.policy_dir)
        except PolicyParseError as exc:
            raise SystemExit(_format_error("Policy test setup failed", exc)) from exc
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
    else:
        try:
            report = run_policy_tests(bundle_path=args.bundle, tests_path=args.tests)
        except PolicyTestRunnerError as exc:
            raise SystemExit(str(exc)) from exc
        report["cases"] = report.pop("tests")
    print(json.dumps(report, indent=2))
    if int(report.get("failures", 0)) > 0:
        raise SystemExit("Policy tests failed")


def _run_policy_schema_version(args: argparse.Namespace) -> None:
    _, metadata = load_policy_bundle(args.policy_dir)
    compatibility = evaluate_bundle_compatibility(
        schema_version=metadata.schema_version
    )
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
    repo = _registry_raw_repo(sqlite_path)
    repo.initialize()
    return repo


def _registry_raw_repo(sqlite_path: Path) -> SQLitePolicyBundleRepository:
    return SQLitePolicyBundleRepository(str(sqlite_path))


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
    rules, metadata = load_policy_bundle(
        args.policy_dir, bundle_name=args.bundle_name, version=args.bundle_version
    )
    metadata.lifecycle = args.lifecycle
    signature_ok, signature_errors, manifest_path = _resolve_signature_verification(
        policy_dir=args.policy_dir,
        manifest_path=args.manifest_path,
        keyring_dir=args.keyring_dir,
        strict=args.signature_strict,
    )
    if args.signature_strict and not signature_ok:
        raise SystemExit(
            f"Bundle signature verification failed: {', '.join(signature_errors)}"
        )
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
    print(
        json.dumps(
            {
                "bundle_name": args.bundle_name,
                "history": repo.get_history(args.bundle_name),
            },
            indent=2,
        )
    )


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
    manifest = BundleReleaseManifest.model_validate(
        json.loads(args.manifest_path.read_text())
    )
    signed = sign_release_manifest(manifest, key_path=args.key_file)
    write_release_manifest(signed, args.output or args.manifest_path)
    print(
        json.dumps(
            {"status": "ok", "manifest_path": str(args.output or args.manifest_path)},
            indent=2,
        )
    )


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
    bundle = repo.get_bundle(args.bundle_id)
    if bundle is None:
        raise SystemExit("Bundle id not found")
    if bundle.metadata.lifecycle == args.target_lifecycle:
        print(json.dumps({"status": "ok", "idempotent": True}, indent=2))
        return
    simulation_scenarios: list[dict[str, Any]] = []
    simulation_report: dict[str, Any] | None = None
    if args.simulation_scenarios:
        simulation_payload = _load_json_file(
            args.simulation_scenarios, "simulation scenarios"
        )
        simulation_scenarios = [
            {"scenario_id": sid, **scenario}
            for sid, scenario in sorted(simulation_payload.items())
        ]
        source_rules = bundle.rules
        source_metadata = bundle.metadata
        if args.target_lifecycle == "active":
            active = repo.get_active_bundle(bundle.metadata.bundle_name)
            if active is not None:
                source_rules = active.rules
                source_metadata = active.metadata
        scenarios = {
            item["scenario_id"]: SimulationScenario(
                action_type=item["action_type"],
                request_id=item.get("request_id"),
                actor_id=item.get("actor_id"),
                attributes=item.get("attributes", {}),
                facts=item.get("facts", {}),
                source_system=item.get("source_system"),
                workflow_stage=item.get("workflow_stage"),
                risk_category=item.get("risk_category"),
            )
            for item in simulation_scenarios
        }
        simulation_report = simulate_bundle_impact(
            scenarios,
            source_rules,
            bundle.rules,
            source_metadata,
            bundle.metadata,
        )
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
            raise SystemExit(
                "Invalid --max-changed-risk-category format. Use risk=max_changed_count"
            )
        thresholds["max_changed_risk_categories"][risk] = int(raw_max)

    settings = load_settings_from_env()
    regression_budget = dict(settings.promotion_gate_max_regressions_by_outcome_type)
    if args.max_block_to_approve_regressions is not None:
        regression_budget["BLOCKED->APPROVED"] = args.max_block_to_approve_regressions
    for item in args.max_regression_budget or []:
        transition, _, raw_max = item.partition("=")
        if not transition or not raw_max:
            raise SystemExit(
                "Invalid --max-regression-budget format. Use BEFORE->AFTER=max_count"
            )
        regression_budget[transition] = int(raw_max)
    gate_failures = evaluate_promotion_gate(
        target_lifecycle=args.target_lifecycle,
        validation_artifact=args.validation_artifact,
        simulation_report=simulation_report,
        break_glass=args.break_glass,
        break_glass_reason=args.break_glass_reason,
        policy=PromotionGatePolicy(
            require_validation_artifact=settings.promotion_gate_require_validation_artifact,
            require_simulation=settings.promotion_gate_require_simulation,
            required_scenario_ids=settings.promotion_gate_required_scenario_ids,
            max_changed_outcomes=(
                args.max_changed_outcomes
                if args.max_changed_outcomes is not None
                else settings.promotion_gate_max_changed_outcomes
            ),
            max_regressions_by_outcome_type=regression_budget,
            break_glass_enabled=settings.promotion_gate_break_glass_enabled,
        ),
    )
    must_block = (not args.break_glass) or any(
        item.code in {"break_glass_reason_required", "break_glass_disabled"}
        for item in gate_failures
    )
    if gate_failures and must_block:
        raise SystemExit(
            json.dumps(
                {
                    "error": "promotion_validation_failed",
                    "failures": [item.__dict__ for item in gate_failures],
                },
                indent=2,
                sort_keys=True,
            )
        )
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
                "simulation_report": simulation_report,
                "thresholds": thresholds,
                "promotion_gate_failures": [item.__dict__ for item in gate_failures],
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


def _run_bundle_rollback(args: argparse.Namespace) -> None:
    repo = _registry_repo(args.sqlite_path)
    target = repo.get_bundle_by_version(args.bundle_name, args.version)
    if target is None:
        raise SystemExit("Bundle version not found")
    repo.rollback_bundle(
        args.bundle_name,
        target.id,
        promoted_by=args.promoted_by,
        promotion_reason=args.promotion_reason,
        validation_artifact=args.validation_artifact,
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "bundle_name": args.bundle_name,
                "active_bundle_id": target.id,
                "version": args.version,
            },
            indent=2,
        )
    )


def _run_registry_fetch_active(args: argparse.Namespace) -> None:
    repo = _registry_repo(args.sqlite_path)
    bundle = repo.get_active_bundle(args.bundle_name)
    if bundle is None:
        raise SystemExit("No active bundle")
    print(
        json.dumps(
            {
                "bundle_id": bundle.id,
                "bundle_name": bundle.metadata.bundle_name,
                "version": bundle.metadata.version,
            },
            indent=2,
        )
    )


def _run_registry_fetch(args: argparse.Namespace) -> None:
    repo = _registry_repo(args.sqlite_path)
    bundle = (
        repo.get_bundle(args.bundle_id)
        if args.bundle_id
        else repo.get_bundle_by_version(args.bundle_name, args.version)
    )
    if bundle is None:
        raise SystemExit("Bundle not found")
    print(
        json.dumps(
            {
                "bundle_id": bundle.id,
                "bundle_name": bundle.metadata.bundle_name,
                "version": bundle.metadata.version,
                "lifecycle": bundle.metadata.lifecycle,
            },
            indent=2,
        )
    )


def _run_registry_upgrade(args: argparse.Namespace) -> None:
    repo = _registry_raw_repo(args.sqlite_path)
    result = repo.upgrade_schema(
        dry_run=args.dry_run, target_version=args.target_version
    )
    print(
        json.dumps(
            {
                "status": "dry-run" if result.dry_run else "ok",
                "initial_version": result.initial_version,
                "target_version": result.target_version,
                "applied_versions": result.applied_versions,
                "pending_versions": result.pending_versions,
            },
            indent=2,
        )
    )


def _run_registry_schema_status(args: argparse.Namespace) -> None:
    repo = _registry_raw_repo(args.sqlite_path)
    print(json.dumps(repo.inspect_schema(), indent=2))


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
                "backup_audit_path": str(artifacts.backup_audit_path)
                if artifacts.backup_audit_path
                else None,
            },
            indent=2,
        )
    )


def _run_registry_verify(args: argparse.Namespace) -> None:
    result = verify_policy_registry_snapshot(
        sqlite_path=args.sqlite_path,
        audit_chain_path=args.audit_chain,
        keyring_dir=args.keyring_dir,
        policy_dir=args.policy_dir,
        active_only=args.active_only,
    )
    payload = {
        "status": "ok" if result.valid else "failed",
        "checks": result.checks,
        "errors": result.errors,
    }
    print(json.dumps(payload, indent=2))
    if not result.valid:
        raise SystemExit("registry verification failed")


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


def _run_audit_archive(args: argparse.Namespace) -> None:
    result = create_audit_archive(
        str(args.audit_path),
        str(args.archive_dir),
        include_active_segment=not args.rotated_only,
    )
    print(json.dumps(result, indent=2))


def _run_audit_verify_archive(args: argparse.Namespace) -> None:
    result = verify_audit_archive(str(args.archive_manifest))
    print(json.dumps(result, indent=2))
    if not result.get("valid", False):
        raise SystemExit("Audit archive verification failed")


def _run_audit_restore_archive(args: argparse.Namespace) -> None:
    restored = restore_audit_archive(
        str(args.archive_manifest), str(args.restore_audit_path)
    )
    verify_result = (
        verify_audit_chain(str(args.restore_audit_path))
        if args.verify_after_restore
        else None
    )
    payload: dict[str, Any] = {"restore": restored}
    if verify_result is not None:
        payload["verify"] = verify_result
    print(json.dumps(payload, indent=2))
    if verify_result is not None and not verify_result.get("valid", False):
        raise SystemExit("Restored audit chain failed verification")


def _run_audit_verify_evidence(args: argparse.Namespace) -> None:
    signer = load_signer_from_keyring_file(args.keyring)
    verifier = AuditRecordVerifier.from_signer(signer)
    result = verify_audit_chain(str(args.audit_path), verifier=verifier)
    print(json.dumps(result, indent=2))
    if not result.get("valid", False):
        raise SystemExit("Audit evidentiary verification failed")


def _run_audit_export_bundle(args: argparse.Namespace) -> None:
    bundle = export_evidence_bundle(str(args.audit_path), args.decision_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": "ok", "output": str(args.output)}, indent=2))


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


def _run_evidence_pack(args: argparse.Namespace) -> None:
    result = build_evidence_pack(
        reference_root=args.reference_root,
        output_dir=args.output_dir,
        clean=args.clean,
    )
    if args.output_zip:
        stable_zip_dir(args.output_dir, args.output_zip)
        result["output_zip"] = str(args.output_zip)
    print(json.dumps(result, indent=2, sort_keys=True))


def _run_replay_drift(args: argparse.Namespace) -> None:
    replay_payload = _load_json_file(args.replay_file, "replay fixture")
    baseline_rules, baseline_meta = load_policy_bundle(args.baseline_policy_dir)
    candidate_rules = baseline_rules
    candidate_meta = baseline_meta
    if args.candidate_policy_dir:
        candidate_rules, candidate_meta = load_policy_bundle(args.candidate_policy_dir)

    baseline_cases = load_replay_cases(
        replay_payload,
        mapping_mode=args.baseline_mapping_mode,
        mapping_config_path=str(args.baseline_mapping_config_path)
        if args.baseline_mapping_config_path
        else None,
    )
    candidate_cases = load_replay_cases(
        replay_payload,
        mapping_mode=args.candidate_mapping_mode or args.baseline_mapping_mode,
        mapping_config_path=(
            str(args.candidate_mapping_config_path)
            if args.candidate_mapping_config_path
            else (
                str(args.baseline_mapping_config_path)
                if args.baseline_mapping_config_path
                else None
            )
        ),
    )
    baseline_result = evaluate_replay_cases(
        cases=baseline_cases, rules=baseline_rules, metadata=baseline_meta
    )
    candidate_result = evaluate_replay_cases(
        cases=candidate_cases, rules=candidate_rules, metadata=candidate_meta
    )
    report = build_drift_report(
        cases=baseline_cases,
        baseline=baseline_result,
        candidate=candidate_result,
        baseline_label=f"{baseline_meta.bundle_name}:{baseline_meta.version}",
        candidate_label=f"{candidate_meta.bundle_name}:{candidate_meta.version}",
    )
    print(json.dumps(report, indent=2))


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
    parser.add_argument(
        "--json", action="store_true", help="Print machine-readable JSON output"
    )
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate without writing side effects (local CLI mode)",
    )
    return parser


def _build_policy_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SENA policy authoring commands")
    sub = parser.add_subparsers(dest="policy_command", required=True)

    init_parser = sub.add_parser(
        "init", help="Initialize a policy bundle from templates"
    )
    init_parser.add_argument(
        "path", type=Path, help="Destination directory for policy files"
    )
    init_parser.add_argument(
        "--force", action="store_true", help="Overwrite existing files"
    )
    init_parser.set_defaults(handler=_run_policy_init)

    validate_parser = sub.add_parser(
        "validate", help="Validate policy syntax and coverage"
    )
    validate_parser.add_argument(
        "--policy-dir", type=Path, required=True, help="Policy directory"
    )
    validate_parser.add_argument("--require-action-type", action="append", default=[])
    validate_parser.add_argument(
        "--explicitly-allowed-action-type", action="append", default=[]
    )
    validate_parser.add_argument(
        "--strict", action="store_true", help="Fail on missing coverage"
    )
    validate_parser.set_defaults(handler=_run_policy_validate)

    test_parser = sub.add_parser(
        "test", help="Run behavior tests against a policy bundle"
    )
    test_parser.add_argument("--policy-dir", type=Path, help="Legacy policy directory")
    test_parser.add_argument("--test-file", type=Path, help="Legacy JSON file with policy cases")
    test_parser.add_argument("--bundle", type=Path, help="Policy bundle directory")
    test_parser.add_argument("--tests", type=Path, help="YAML/JSON test manifest with 'tests' list")
    test_parser.set_defaults(handler=_run_policy_test)

    schema_parser = sub.add_parser(
        "schema-version", help="Inspect bundle schema version"
    )
    schema_parser.add_argument(
        "--policy-dir", type=Path, required=True, help="Policy directory"
    )
    schema_parser.set_defaults(handler=_run_policy_schema_version)

    migrate_parser = sub.add_parser(
        "migrate", help="Migrate bundle manifest/rules to a target schema"
    )
    migrate_parser.add_argument(
        "--policy-dir", type=Path, required=True, help="Policy directory"
    )
    migrate_parser.add_argument(
        "--target-schema-version", default=CURRENT_BUNDLE_SCHEMA_VERSION
    )
    migrate_parser.add_argument(
        "--dry-run", action="store_true", help="Preview migration changes only"
    )
    migrate_parser.set_defaults(handler=_run_policy_migrate)

    compatibility_parser = sub.add_parser(
        "verify-compatibility", help="Verify runtime compatibility"
    )
    compatibility_parser.add_argument(
        "--policy-dir", type=Path, required=True, help="Policy directory"
    )
    compatibility_parser.add_argument(
        "--runtime-version", default=SENA_VERSION, help="Evaluator runtime version"
    )
    compatibility_parser.add_argument("--min-evaluator-version")
    compatibility_parser.add_argument("--max-evaluator-version")
    compatibility_parser.set_defaults(handler=_run_policy_verify_compatibility)

    return parser


def _build_registry_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SENA sqlite policy registry commands")
    parser.add_argument("--sqlite-path", type=Path, required=True)
    sub = parser.add_subparsers(dest="registry_command", required=True)

    upgrade = sub.add_parser("upgrade", help="Apply ordered registry schema migrations")
    upgrade.add_argument("--target-version", type=int)
    upgrade.add_argument(
        "--dry-run", action="store_true", help="Plan migrations without applying"
    )
    upgrade.set_defaults(handler=_run_registry_upgrade)

    schema_status = sub.add_parser(
        "schema-status", help="Inspect current schema migration state"
    )
    schema_status.set_defaults(handler=_run_registry_schema_status)

    register = sub.add_parser("register")
    register.add_argument("--policy-dir", type=Path, required=True)
    register.add_argument("--bundle-name", required=True)
    register.add_argument("--bundle-version", required=True)
    register.add_argument(
        "--lifecycle",
        default="draft",
        choices=["draft", "candidate", "approved", "active", "deprecated"],
    )
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
    validate.add_argument(
        "--target-lifecycle",
        required=True,
        choices=["candidate", "approved", "active", "deprecated"],
    )
    validate.add_argument("--validation-artifact")
    validate.set_defaults(handler=_run_registry_validate)

    promote = sub.add_parser("promote")
    promote.add_argument("--bundle-id", type=int, required=True)
    promote.add_argument(
        "--target-lifecycle",
        required=True,
        choices=["candidate", "approved", "active", "deprecated"],
    )
    promote.add_argument("--promoted-by", required=True)
    promote.add_argument("--promotion-reason", required=True)
    promote.add_argument("--validation-artifact")
    promote.add_argument("--simulation-scenarios", type=Path)
    promote.add_argument("--max-changed-outcomes", type=int)
    promote.add_argument("--max-block-to-approve-regressions", type=int)
    promote.add_argument("--max-regression-budget", action="append")
    promote.add_argument("--max-missing-scenario-coverage", type=int)
    promote.add_argument("--required-risk-category", action="append")
    promote.add_argument("--max-changed-risk-category", action="append")
    promote.add_argument("--break-glass", action="store_true")
    promote.add_argument("--break-glass-reason")
    promote.add_argument("--approver-attestation", action="append")
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

    verify = sub.add_parser("verify")
    verify.add_argument("--audit-chain", type=Path)
    verify.add_argument("--policy-dir", type=Path)
    verify.add_argument("--keyring-dir", type=Path)
    verify.add_argument("--active-only", action="store_true")
    verify.set_defaults(handler=_run_registry_verify)

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
    parser = argparse.ArgumentParser(
        description="SENA bundle release manifest commands"
    )
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


def _build_bundle_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SENA bundle operations")
    sub = parser.add_subparsers(dest="bundle_command", required=True)
    rollback = sub.add_parser("rollback")
    rollback.add_argument("--sqlite-path", type=Path, required=True)
    rollback.add_argument("--bundle-name", required=True)
    rollback.add_argument("--version", required=True)
    rollback.add_argument("--promoted-by", default="system")
    rollback.add_argument("--promotion-reason", default="manual rollback")
    rollback.add_argument("--validation-artifact", default="rollback")
    rollback.set_defaults(handler=_run_bundle_rollback)
    return parser


def _build_audit_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SENA audit chain operational commands"
    )
    parser.add_argument(
        "--audit-path", type=Path, required=True, help="Path to active JSONL audit sink"
    )
    sub = parser.add_subparsers(dest="audit_command", required=True)

    verify = sub.add_parser(
        "verify", help="Verify full chain integrity across rotated segments"
    )
    verify.set_defaults(handler=_run_audit_verify)

    summarize = sub.add_parser("summarize", help="Summarize chain/manifest status")
    summarize.set_defaults(handler=_run_audit_summarize)

    locate = sub.add_parser(
        "locate-decision", help="Locate a specific decision id within audit chain"
    )
    locate.add_argument("decision_id")
    locate.set_defaults(handler=_run_audit_locate_decision)

    archive = sub.add_parser(
        "archive",
        help="Create deterministic local archive artifacts for rotated/live segments",
    )
    archive.add_argument("--archive-dir", type=Path, required=True)
    archive.add_argument(
        "--rotated-only", action="store_true", help="Archive rotated segments only"
    )
    archive.set_defaults(handler=_run_audit_archive)

    verify_archive = sub.add_parser(
        "verify-archive", help="Verify archive manifest checksums and chain continuity"
    )
    verify_archive.add_argument("--archive-manifest", type=Path, required=True)
    verify_archive.set_defaults(handler=_run_audit_verify_archive)

    restore_archive = sub.add_parser(
        "restore-archive", help="Restore an archived chain into a local audit sink path"
    )
    restore_archive.add_argument("--archive-manifest", type=Path, required=True)
    restore_archive.add_argument("--restore-audit-path", type=Path, required=True)
    restore_archive.add_argument("--verify-after-restore", action="store_true")
    restore_archive.set_defaults(handler=_run_audit_restore_archive)

    verify_evidence = sub.add_parser(
        "verify-evidence",
        help="Verify chain integrity plus per-record signatures and trusted timestamp hashes",
    )
    verify_evidence.add_argument("--keyring", type=Path, required=True)
    verify_evidence.set_defaults(handler=_run_audit_verify_evidence)

    export_bundle = sub.add_parser(
        "export-evidence-bundle",
        help="Export evidentiary bundle JSON for one decision",
    )
    export_bundle.add_argument("decision_id")
    export_bundle.add_argument("--output", type=Path, required=True)
    export_bundle.set_defaults(handler=_run_audit_export_bundle)
    return parser


def _build_evidence_pack_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SENA policy release evidence pack commands"
    )
    default_reference = (
        Path(__file__).resolve().parents[3] / "examples" / "design_partner_reference"
    )
    parser.add_argument("--reference-root", type=Path, default=default_reference)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output-zip", type=Path)
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete existing output directory before generating",
    )
    parser.set_defaults(handler=_run_evidence_pack)
    return parser


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "production-check":
        parser = argparse.ArgumentParser(
            description="SENA production-readiness validation"
        )
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
    if len(sys.argv) > 1 and sys.argv[1] == "bundle":
        parser = _build_bundle_parser()
        args = parser.parse_args(sys.argv[2:])
        args.handler(args)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "audit":
        parser = _build_audit_parser()
        args = parser.parse_args(sys.argv[2:])
        args.handler(args)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "evidence-pack":
        parser = _build_evidence_pack_parser()
        args = parser.parse_args(sys.argv[2:])
        args.handler(args)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "replay":
        parser = argparse.ArgumentParser(
            description="SENA replay and drift detection commands"
        )
        sub = parser.add_subparsers(dest="replay_command", required=True)
        drift = sub.add_parser("drift")
        drift.add_argument("--replay-file", type=Path, required=True)
        drift.add_argument("--baseline-policy-dir", type=Path, required=True)
        drift.add_argument("--candidate-policy-dir", type=Path)
        drift.add_argument(
            "--baseline-mapping-mode", choices=["jira", "servicenow", "webhook"]
        )
        drift.add_argument("--baseline-mapping-config-path", type=Path)
        drift.add_argument(
            "--candidate-mapping-mode", choices=["jira", "servicenow", "webhook"]
        )
        drift.add_argument("--candidate-mapping-config-path", type=Path)
        drift.set_defaults(handler=_run_replay_drift)
        args = parser.parse_args(sys.argv[2:])
        args.handler(args)
        return

    parser = _build_evaluate_parser()
    args = parser.parse_args()
    _run_evaluate(args)


if __name__ == "__main__":
    main()
