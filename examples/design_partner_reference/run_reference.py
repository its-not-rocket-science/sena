from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from sena.audit.chain import append_audit_record, verify_audit_chain
from sena.audit.sinks import JsonlFileAuditSink, RotationPolicy
from sena.engine.evaluator import PolicyEvaluator
from sena.engine.review_package import build_decision_review_package
from sena.engine.simulation import SimulationScenario, simulate_bundle_impact
from sena.integrations.base import DecisionPayload
from sena.integrations.servicenow import ServiceNowConnector, load_servicenow_mapping_config
from sena.policy.lifecycle import validate_promotion
from sena.policy.parser import load_policy_bundle
from sena.policy.release_signing import (
    generate_release_manifest,
    sign_release_manifest,
    verify_release_manifest,
    write_release_manifest,
)

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"
ARTIFACTS = ROOT / "artifacts"
POLICY_CANDIDATE = ROOT / "policy_bundles" / "candidate"
POLICY_ACTIVE = ROOT / "policy_bundles" / "active"
KEYRING = ROOT / "keyring"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def _event_files() -> list[Path]:
    return sorted(FIXTURES.glob("servicenow_event_*.json"))


def run() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    KEYRING.mkdir(parents=True, exist_ok=True)

    trusted_key_path = KEYRING / "design-partner-ops.key"
    if not trusted_key_path.exists():
        trusted_key_path.write_text("acme-design-partner-reference-signing-key\n", encoding="utf-8")

    connector = ServiceNowConnector(config=load_servicenow_mapping_config(str(ROOT / "integration" / "servicenow_mapping.yaml")))

    candidate_rules, candidate_meta = load_policy_bundle(POLICY_CANDIDATE)
    active_rules, active_meta = load_policy_bundle(POLICY_ACTIVE)

    # Signed bundle release artifact.
    manifest = generate_release_manifest(
        POLICY_ACTIVE,
        key_id="design-partner-ops",
        signer_name="acme-risk-ops",
        compatibility_notes="Validated against SENA supported schema v1 and runtime compatibility range.",
        migration_notes="Promotion from candidate after simulation gate approval.",
    )
    signed_manifest = sign_release_manifest(manifest, key_path=trusted_key_path)
    manifest_path = ARTIFACTS / "release-manifest.json"
    write_release_manifest(signed_manifest, manifest_path)
    signature_verification = verify_release_manifest(
        POLICY_ACTIVE,
        manifest_path=manifest_path,
        keyring_dir=KEYRING,
        strict=True,
    )

    # Simulation before promotion.
    scenario_rows = _load_json(FIXTURES / "simulation_scenarios.json")
    scenarios = {
        name: SimulationScenario(
            action_type=payload["action_type"],
            request_id=payload.get("request_id"),
            actor_id=payload.get("actor_id"),
            attributes=payload.get("attributes", {}),
            facts=payload.get("facts", {}),
            source_system=payload.get("attributes", {}).get("source_system"),
            workflow_stage=payload.get("attributes", {}).get("workflow_stage"),
            risk_category=payload.get("attributes", {}).get("risk_category"),
        )
        for name, payload in scenario_rows.items()
    }
    simulation_report = simulate_bundle_impact(scenarios, candidate_rules, active_rules, candidate_meta, active_meta)
    _write_json(ARTIFACTS / "simulation-report.json", simulation_report)

    promotion = validate_promotion(
        candidate_meta.lifecycle,
        active_meta.lifecycle,
        candidate_rules,
        active_rules,
        validation_artifact="simulation-report.json",
        signature_verified=signature_verification.valid,
        signature_verification_strict=True,
    )
    promotion_payload = {
        "candidate_bundle": asdict(candidate_meta),
        "active_bundle": asdict(active_meta),
        "signature_verification": asdict(signature_verification),
        "promotion_validation": asdict(promotion),
    }
    _write_json(ARTIFACTS / "promotion-validation.json", promotion_payload)

    if not promotion.valid:
        raise RuntimeError(f"Promotion validation failed: {promotion.errors}")

    # Evaluation flow + audit sink.
    audit_sink = JsonlFileAuditSink(
        path=str(ARTIFACTS / "audit" / "audit.jsonl"),
        append_only=True,
        rotation=RotationPolicy(max_file_bytes=1024 * 1024),
    )
    evaluations: list[dict] = []
    evaluator = PolicyEvaluator(active_rules, policy_bundle=active_meta)

    for fixture in _event_files():
        event = _load_json(fixture)
        event["raw_body"] = b""
        transformed = connector.handle_event(event)
        proposal = transformed["action_proposal"]
        trace = evaluator.evaluate(proposal, facts={})

        persisted = append_audit_record(audit_sink, trace.audit_record.__dict__ if trace.audit_record else {})
        if trace.audit_record:
            trace.audit_record.chain_hash = persisted.get("chain_hash")
            trace.audit_record.previous_chain_hash = persisted.get("previous_chain_hash")
            trace.audit_record.storage_sequence_number = persisted.get("storage_sequence_number")

        decision_delivery = connector.send_decision(
            DecisionPayload(
                decision_id=trace.decision_id,
                request_id=trace.request_id,
                action_type=trace.action_type,
                matched_rule_ids=[item.rule_id for item in trace.matched_rules],
                summary=trace.summary,
            )
        )

        review_package = build_decision_review_package(trace)
        review_file = ARTIFACTS / "review_packages" / f"{trace.request_id or trace.decision_id}.json"
        _write_json(review_file, review_package)

        evaluations.append(
            {
                "fixture": fixture.name,
                "normalized_event": transformed["normalized_event"],
                "decision": trace.to_dict(),
                "delivery": decision_delivery,
                "review_package_file": str(review_file.relative_to(ROOT)),
            }
        )

    _write_json(ARTIFACTS / "evaluation-results.json", evaluations)
    _write_json(ARTIFACTS / "audit-chain-verification.json", verify_audit_chain(audit_sink))

    lock_file = ARTIFACTS / "audit" / "audit.jsonl.lock"
    if lock_file.exists():
        lock_file.unlink()



if __name__ == "__main__":
    run()
