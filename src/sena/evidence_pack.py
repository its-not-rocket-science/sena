from __future__ import annotations

import json
import shutil
import sys
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sena import __version__ as SENA_VERSION
from sena.audit.chain import append_audit_record, verify_audit_chain
from sena.audit.sinks import JsonlFileAuditSink, RotationPolicy
from sena.engine.evaluator import PolicyEvaluator
from sena.engine.review_package import build_decision_review_package
from sena.engine.simulation import SimulationScenario, simulate_bundle_impact
from sena.integrations.base import DecisionPayload
from sena.integrations.jira import (
    AllowAllJiraWebhookVerifier,
    JiraConnector,
    load_jira_mapping_config,
)
from sena.integrations.servicenow import (
    ServiceNowConnector,
    load_servicenow_mapping_config,
)
from sena.policy.lifecycle import diff_rule_sets, validate_promotion
from sena.policy.parser import load_policy_bundle
from sena.policy.release_signing import (
    generate_release_manifest,
    sign_release_manifest,
    verify_release_manifest,
    write_release_manifest,
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def stable_zip_dir(source_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source_dir.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(source_dir)
            info = zipfile.ZipInfo(str(rel).replace("\\", "/"))
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, path.read_bytes())


def build_evidence_pack(
    *, reference_root: Path, output_dir: Path, clean: bool = False
) -> dict[str, Any]:
    fixtures_dir = reference_root / "fixtures"
    integration_dir = reference_root / "integration"
    candidate_dir = reference_root / "policy_bundles" / "candidate"
    active_dir = reference_root / "policy_bundles" / "active"

    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    artifacts_dir = output_dir / "artifacts"
    traces_dir = artifacts_dir / "evaluation_traces"
    review_dir = artifacts_dir / "review_packages"
    integration_examples_dir = artifacts_dir / "integration_examples"
    keyring_dir = output_dir / "keyring"
    keyring_dir.mkdir(parents=True, exist_ok=True)

    trusted_key = keyring_dir / "design-partner-ops.key"
    if not trusted_key.exists():
        trusted_key.write_text(
            "acme-design-partner-reference-signing-key\n", encoding="utf-8"
        )

    candidate_rules, candidate_meta = load_policy_bundle(candidate_dir)
    active_rules, active_meta = load_policy_bundle(active_dir)

    write_json(
        artifacts_dir / "bundle_metadata.json",
        {"candidate": asdict(candidate_meta), "active": asdict(active_meta)},
    )

    manifest = generate_release_manifest(
        active_dir,
        key_id="design-partner-ops",
        signer_name="acme-risk-ops",
        compatibility_notes="Validated against SENA supported schema v1 and runtime compatibility range.",
        migration_notes="Promotion from candidate after simulation gate approval.",
    )
    signed_manifest = sign_release_manifest(manifest, key_path=trusted_key)
    manifest_path = artifacts_dir / "release_manifest.json"
    write_release_manifest(signed_manifest, manifest_path)
    signature_verification = verify_release_manifest(
        active_dir, manifest_path=manifest_path, keyring_dir=keyring_dir, strict=True
    )
    write_json(
        artifacts_dir / "signature_verification.json", asdict(signature_verification)
    )

    write_json(
        artifacts_dir / "rule_diff.json",
        asdict(diff_rule_sets(candidate_rules, active_rules)),
    )

    scenario_rows = load_json(fixtures_dir / "simulation_scenarios.json")
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
        for name, payload in sorted(scenario_rows.items())
    }
    simulation_report = simulate_bundle_impact(
        scenarios, candidate_rules, active_rules, candidate_meta, active_meta
    )
    write_json(artifacts_dir / "simulation_summary.json", simulation_report)

    promotion = validate_promotion(
        candidate_meta.lifecycle,
        active_meta.lifecycle,
        candidate_rules,
        active_rules,
        validation_artifact="simulation_summary.json",
        signature_verified=signature_verification.valid,
        signature_verification_strict=True,
    )
    write_json(
        artifacts_dir / "promotion_validation.json",
        {
            "candidate_bundle": asdict(candidate_meta),
            "active_bundle": asdict(active_meta),
            "signature_verification": asdict(signature_verification),
            "promotion_validation": asdict(promotion),
        },
    )

    connectors = {
        "servicenow": ServiceNowConnector(
            config=load_servicenow_mapping_config(
                str(integration_dir / "servicenow_mapping.yaml")
            )
        ),
        "jira": JiraConnector(
            config=load_jira_mapping_config(str(integration_dir / "jira_mapping.yaml")),
            verifier=AllowAllJiraWebhookVerifier(),
        ),
    }
    evaluator = PolicyEvaluator(active_rules, policy_bundle=active_meta)
    audit_sink = JsonlFileAuditSink(
        path=str(artifacts_dir / "audit" / "audit.jsonl"),
        append_only=True,
        rotation=RotationPolicy(max_file_bytes=1024 * 1024),
    )

    traces: list[dict[str, Any]] = []
    integration_examples: list[dict[str, Any]] = []
    for fixture in sorted(fixtures_dir.glob("*_event_*.json")):
        source_system = fixture.name.split("_event_", 1)[0]
        connector = connectors.get(source_system)
        if connector is None:
            continue
        event = load_json(fixture)
        event["raw_body"] = b""
        transformed = connector.handle_event(event)
        trace = evaluator.evaluate(transformed["action_proposal"], facts={})
        persisted = append_audit_record(
            audit_sink, trace.audit_record.__dict__ if trace.audit_record else {}
        )
        if trace.audit_record:
            trace.audit_record.chain_hash = persisted.get("chain_hash")
            trace.audit_record.previous_chain_hash = persisted.get(
                "previous_chain_hash"
            )
            trace.audit_record.storage_sequence_number = persisted.get(
                "storage_sequence_number"
            )

        delivery = connector.send_decision(
            DecisionPayload(
                decision_id=trace.decision_id,
                request_id=trace.request_id,
                action_type=trace.action_type,
                matched_rule_ids=[item.rule_id for item in trace.matched_rules],
                summary=trace.summary,
            )
        )

        trace_path = traces_dir / f"{trace.request_id or trace.decision_id}.json"
        write_json(trace_path, trace.to_dict())
        traces.append(
            {
                "fixture": fixture.name,
                "trace_file": str(trace_path.relative_to(output_dir)),
            }
        )

        review_path = review_dir / f"{trace.request_id or trace.decision_id}.json"
        write_json(review_path, build_decision_review_package(trace))

        integration_payload = {
            "fixture": fixture.name,
            "source_system": source_system,
            "normalized_event": transformed["normalized_event"],
            "decision_delivery": delivery,
        }
        integration_examples.append(integration_payload)
        write_json(
            integration_examples_dir / f"{fixture.stem}.json", integration_payload
        )

    write_json(artifacts_dir / "evaluation_trace_index.json", traces)
    write_json(artifacts_dir / "integration_examples_index.json", integration_examples)
    audit_verification = verify_audit_chain(audit_sink)
    write_json(artifacts_dir / "audit_verification.json", audit_verification)

    write_json(
        artifacts_dir / "runtime_metadata.json",
        {
            "python_version": sys.version,
            "sena_version": SENA_VERSION,
            "source_reference_root": str(reference_root),
        },
    )

    (output_dir / "SUMMARY.md").write_text(
        "\n".join(
            [
                "# SENA Evidence Pack",
                "",
                "## Included artifacts",
                "- bundle_metadata.json",
                "- signature_verification.json",
                "- rule_diff.json",
                "- simulation_summary.json",
                "- promotion_validation.json",
                "- evaluation_traces/*.json",
                "- audit_verification.json",
                "- integration_examples/*.json",
                "- flagship workflow examples for Jira + ServiceNow",
                "- review_packages/*.json",
                "- runtime_metadata.json",
                "",
                "## Result highlights",
                f"- Signature verified: `{signature_verification.valid}`",
                f"- Promotion valid: `{promotion.valid}`",
                f"- Changed simulation scenarios: `{simulation_report['changed_scenarios']}` / `{simulation_report['total_scenarios']}`",
                f"- Audit chain valid: `{audit_verification.get('valid', False)}`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "output_dir": str(output_dir),
        "artifacts_dir": str(artifacts_dir),
        "summary": {
            "signature_verified": signature_verification.valid,
            "promotion_valid": promotion.valid,
            "audit_valid": audit_verification.get("valid", False),
            "changed_scenarios": simulation_report["changed_scenarios"],
            "total_scenarios": simulation_report["total_scenarios"],
        },
    }
