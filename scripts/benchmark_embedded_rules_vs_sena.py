from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sena.audit.chain import append_audit_record, summarize_audit_chain
from sena.audit.sinks import JsonlFileAuditSink
from sena.core.models import ActionProposal, PolicyBundleMetadata, PolicyRule
from sena.engine.evaluator import PolicyEvaluator
from sena.engine.review_package import build_decision_review_package
from sena.engine.simulation import SimulationScenario, simulate_bundle_impact
from sena.integrations.jira import AllowAllJiraWebhookVerifier, JiraConnector, load_jira_mapping_config
from sena.integrations.servicenow import ServiceNowConnector, load_servicenow_mapping_config
from sena.policy.lifecycle import diff_rule_sets, validate_promotion
from sena.policy.parser import load_policy_bundle

ROOT = Path(__file__).resolve().parents[1]
DESIGN_PARTNER = ROOT / "examples" / "design_partner_reference"


def _write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_simulation_scenarios(path: Path) -> dict[str, SimulationScenario]:
    raw = _load_json(path)
    return {
        scenario_id: SimulationScenario(
            action_type=payload["action_type"],
            request_id=payload.get("request_id"),
            actor_id=payload.get("actor_id"),
            attributes=payload.get("attributes", {}),
            facts=payload.get("facts", {}),
            source_system=payload.get("attributes", {}).get("source_system"),
            workflow_stage=payload.get("attributes", {}).get("workflow_stage"),
            risk_category=payload.get("attributes", {}).get("risk_category"),
        )
        for scenario_id, payload in raw.items()
    }


def _evaluate_with_rules(
    scenarios: dict[str, SimulationScenario],
    rules: list[PolicyRule],
    metadata: PolicyBundleMetadata,
) -> dict[str, dict[str, Any]]:
    evaluator = PolicyEvaluator(rules, policy_bundle=metadata)
    outputs: dict[str, dict[str, Any]] = {}
    for scenario_id, scenario in sorted(scenarios.items()):
        proposal = ActionProposal(
            action_type=scenario.action_type,
            request_id=scenario.request_id,
            actor_id=scenario.actor_id,
            attributes=scenario.attributes,
        )
        trace = evaluator.evaluate(proposal, scenario.facts)
        outputs[scenario_id] = {
            "outcome": trace.outcome.value,
            "matched_rule_ids": [item.rule_id for item in trace.matched_rules],
            "decision_hash": trace.decision_hash,
            "bundle_name": trace.policy_bundle.bundle_name if trace.policy_bundle else None,
            "bundle_version": trace.policy_bundle.version if trace.policy_bundle else None,
            "bundle_integrity_sha256": trace.policy_bundle.integrity_sha256 if trace.policy_bundle else None,
        }
    return outputs


def _extract_event_proposals() -> list[dict[str, Any]]:
    jira = JiraConnector(
        config=load_jira_mapping_config(str(DESIGN_PARTNER / "integration" / "jira_mapping.yaml")),
        verifier=AllowAllJiraWebhookVerifier(),
    )
    servicenow = ServiceNowConnector(
        config=load_servicenow_mapping_config(str(DESIGN_PARTNER / "integration" / "servicenow_mapping.yaml"))
    )

    fixtures = [
        ("jira", DESIGN_PARTNER / "fixtures" / "jira_event_high_risk_missing_cab.json", jira),
        ("jira", DESIGN_PARTNER / "fixtures" / "jira_event_low_risk_with_cab.json", jira),
        ("servicenow", DESIGN_PARTNER / "fixtures" / "servicenow_event_high_risk_missing_cab.json", servicenow),
        (
            "servicenow",
            DESIGN_PARTNER / "fixtures" / "servicenow_event_emergency_privileged_no_chain.json",
            servicenow,
        ),
        ("servicenow", DESIGN_PARTNER / "fixtures" / "servicenow_event_low_risk_with_cab.json", servicenow),
    ]

    records: list[dict[str, Any]] = []
    for system_name, path, connector in fixtures:
        event = _load_json(path)
        payload = event["payload"]
        headers = event.get("headers", {})
        mapped = connector.handle_event({"headers": headers, "payload": payload, "raw_body": json.dumps(payload).encode("utf-8")})
        proposal = mapped["action_proposal"]
        records.append(
            {
                "source_system": system_name,
                "fixture": path.name,
                "action_type": proposal.action_type,
                "request_id": proposal.request_id,
                "actor_id": proposal.actor_id,
                "actor_role": proposal.actor_role,
                "attributes": proposal.attributes,
                "facts": {},
            }
        )
    return records


def _run_replayability_and_audit_bundle(
    rules: list[PolicyRule],
    metadata: PolicyBundleMetadata,
    event_proposals: list[dict[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    evaluator = PolicyEvaluator(rules, policy_bundle=metadata)
    audit_path = output_dir / "audit" / "sena_audit.jsonl"
    if audit_path.exists():
        audit_path.unlink()

    sink = JsonlFileAuditSink(path=str(audit_path), append_only=True)
    reviews: list[dict[str, Any]] = []
    replay_rows: list[dict[str, Any]] = []

    for row in event_proposals:
        proposal = ActionProposal(
            action_type=row["action_type"],
            request_id=row["request_id"],
            actor_id=row["actor_id"],
            actor_role=row.get("actor_role"),
            attributes=row["attributes"],
        )
        first = evaluator.evaluate(proposal, facts=row["facts"])
        second = evaluator.evaluate(proposal, facts=row["facts"])

        persisted = append_audit_record(sink, first.audit_record.__dict__ if first.audit_record else {})
        replay_rows.append(
            {
                "fixture": row["fixture"],
                "source_system": row["source_system"],
                "first_outcome": first.outcome.value,
                "second_outcome": second.outcome.value,
                "deterministic_replay": first.outcome == second.outcome and first.decision_hash == second.decision_hash,
                "decision_hash": first.decision_hash,
                "bundle_version": first.policy_bundle.version if first.policy_bundle else None,
                "bundle_integrity_sha256": first.policy_bundle.integrity_sha256 if first.policy_bundle else None,
                "audit_chain_hash": persisted.get("chain_hash"),
            }
        )
        reviews.append(build_decision_review_package(first))

    _write_json(output_dir / "review_packages.json", reviews)
    _write_json(output_dir / "replayability.json", replay_rows)
    audit_summary = summarize_audit_chain(sink)
    _write_json(output_dir / "audit_summary.json", audit_summary)
    return {
        "replayability": replay_rows,
        "audit_summary": audit_summary,
        "audit_path": str(audit_path.relative_to(ROOT)),
    }


def run(output_dir: Path, clean: bool) -> None:
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    candidate_rules, candidate_meta = load_policy_bundle(DESIGN_PARTNER / "policy_bundles" / "candidate")
    active_rules, active_meta = load_policy_bundle(DESIGN_PARTNER / "policy_bundles" / "active")
    scenarios = _load_simulation_scenarios(DESIGN_PARTNER / "fixtures" / "simulation_scenarios.json")

    sena_impact = simulate_bundle_impact(scenarios, candidate_rules, active_rules, candidate_meta, active_meta)
    _write_json(output_dir / "sena_policy_change_impact.json", sena_impact)

    embedded_before = PolicyBundleMetadata(
        bundle_name="embedded-servicenow-workflow",
        version="candidate",
        loaded_from="workflow_engine",
        lifecycle="active",
    )
    embedded_after = PolicyBundleMetadata(
        bundle_name="embedded-servicenow-workflow",
        version="active",
        loaded_from="workflow_engine",
        lifecycle="active",
    )
    embedded_before_eval = _evaluate_with_rules(scenarios, candidate_rules, embedded_before)
    embedded_after_eval = _evaluate_with_rules(scenarios, active_rules, embedded_after)
    embedded_diff = diff_rule_sets(candidate_rules, active_rules)
    embedded_impact = {
        "before": embedded_before_eval,
        "after": embedded_after_eval,
        "diff": asdict(embedded_diff),
        "visibility_constraints": {
            "global_impact_report_available": False,
            "explanation": "Per-workflow rule files can be evaluated, but there is no centralized grouped impact report artifact like simulate_bundle_impact().",
        },
    }
    _write_json(output_dir / "embedded_policy_change_impact.json", embedded_impact)

    event_proposals = _extract_event_proposals()
    cross_system = {
        "input_fixtures": [row["fixture"] for row in event_proposals],
        "source_systems": sorted({row["source_system"] for row in event_proposals}),
        "action_types": sorted({row["action_type"] for row in event_proposals}),
        "single_bundle": {
            "bundle_name": active_meta.bundle_name,
            "bundle_version": active_meta.version,
        },
        "evaluation_rows": _evaluate_with_rules(
            {
                row["fixture"]: SimulationScenario(
                    action_type=row["action_type"],
                    request_id=row["request_id"],
                    actor_id=row["actor_id"],
                    attributes=row["attributes"],
                    facts=row["facts"],
                    source_system=row["source_system"],
                    workflow_stage=row["attributes"].get("workflow_stage"),
                    risk_category=row["attributes"].get("risk_category"),
                )
                for row in event_proposals
            },
            active_rules,
            active_meta,
        ),
    }
    _write_json(output_dir / "cross_system_reuse.json", cross_system)

    sena_ops = _run_replayability_and_audit_bundle(active_rules, active_meta, event_proposals, output_dir / "sena")

    embedded_replay_rows = [
        {
            "fixture": row["fixture"],
            "source_system": row["source_system"],
            "bundle_version": None,
            "bundle_integrity_sha256": None,
            "audit_chain_hash": None,
            "note": "Representative embedded workflow log row lacks portable bundle identity and tamper-evident chain fields.",
        }
        for row in event_proposals
    ]
    _write_json(output_dir / "embedded_replayability_placeholder.json", embedded_replay_rows)

    promotion_with_gate = validate_promotion(
        candidate_meta.lifecycle,
        active_meta.lifecycle,
        candidate_rules,
        active_rules,
        validation_artifact="simulation-report.json",
        signature_verified=True,
        signature_verification_strict=True,
    )
    promotion_without_gate = validate_promotion(
        candidate_meta.lifecycle,
        active_meta.lifecycle,
        candidate_rules,
        active_rules,
        validation_artifact=None,
        signature_verified=False,
        signature_verification_strict=True,
    )
    _write_json(
        output_dir / "promotion_governance.json",
        {
            "sena_with_required_artifacts": asdict(promotion_with_gate),
            "sena_without_required_artifacts": asdict(promotion_without_gate),
            "embedded_workflow_baseline": {
                "automatic_promotion_gate": False,
                "note": "No repository-level validator exists for embedded workflow edits; governance must be enforced out-of-band.",
            },
        },
    )

    summary = {
        "artifacts_dir": str(output_dir.relative_to(ROOT)),
        "policy_change_impact": {
            "sena_changed_scenarios": sena_impact["changed_scenarios"],
            "embedded_changed_rule_ids": embedded_impact["diff"]["changed_rule_ids"],
        },
        "replayability": {
            "sena_all_replays_deterministic": all(item["deterministic_replay"] for item in sena_ops["replayability"]),
            "embedded_has_bundle_identity": False,
        },
        "auditability": {
            "sena_audit_chain_valid": bool(sena_ops["audit_summary"].get("valid")),
            "embedded_tamper_evidence_available": False,
        },
        "cross_system_reuse": {
            "source_systems": cross_system["source_systems"],
            "single_bundle": cross_system["single_bundle"],
        },
        "promotion_governance": {
            "with_artifacts_valid": promotion_with_gate.valid,
            "without_artifacts_valid": promotion_without_gate.valid,
            "without_artifacts_errors": promotion_without_gate.errors,
        },
    }
    _write_json(output_dir / "summary.json", summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Reproducible governance benchmark comparing centralized SENA policy evaluation "
            "to a representative embedded-workflow-rules baseline."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/examples/artifacts/embedded_rules_vs_sena"),
        help="Directory where benchmark artifacts are written.",
    )
    parser.add_argument("--clean", action="store_true", help="Delete output directory before writing artifacts.")
    args = parser.parse_args()

    run(output_dir=args.output_dir.resolve(), clean=args.clean)
