from __future__ import annotations

import json
from pathlib import Path

from sena.audit.chain import append_audit_record, verify_audit_chain
from sena.audit.sinks import JsonlFileAuditSink, RotationPolicy
from sena.engine.evaluator import PolicyEvaluator
from sena.engine.replay import export_canonical_replay_artifact
from sena.integrations.servicenow import ServiceNowConnector, load_servicenow_mapping_config
from sena.policy.parser import load_policy_bundle

ROOT = Path(__file__).resolve().parent
ARTIFACTS = ROOT / "artifacts"
AUDIT_PATH = ARTIFACTS / "audit" / "audit.jsonl"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def run() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    connector = ServiceNowConnector(
        config=load_servicenow_mapping_config(
            str(ROOT.parent / "design_partner_reference" / "integration" / "servicenow_mapping.yaml")
        )
    )
    bundle_path = ROOT.parent / "design_partner_reference" / "policy_bundles" / "active"
    rules, metadata = load_policy_bundle(bundle_path)
    evaluator = PolicyEvaluator(rules, policy_bundle=metadata)

    webhook_payload = _load_json(ROOT / "servicenow_webhook_payload.json")
    event = connector.handle_event(
        {
            "headers": {"x-servicenow-delivery-id": "flagship-workflow-001"},
            "payload": webhook_payload,
            "raw_body": b"",
        }
    )

    trace = evaluator.evaluate(event["action_proposal"], facts={})

    audit_sink = JsonlFileAuditSink(
        path=str(AUDIT_PATH),
        append_only=True,
        rotation=RotationPolicy(max_file_bytes=1024 * 1024),
    )
    persisted = append_audit_record(audit_sink, trace.audit_record.__dict__ if trace.audit_record else {})
    if trace.audit_record:
        trace.audit_record.chain_hash = persisted.get("chain_hash")
        trace.audit_record.previous_chain_hash = persisted.get("previous_chain_hash")
        trace.audit_record.storage_sequence_number = persisted.get("storage_sequence_number")

    _write_json(ARTIFACTS / "normalized-event.json", event["normalized_event"])
    _write_json(ARTIFACTS / "decision-trace.json", trace.to_dict())
    _write_json(ARTIFACTS / "canonical-replay-artifact.json", export_canonical_replay_artifact(trace))
    _write_json(ARTIFACTS / "audit-verification.json", verify_audit_chain(audit_sink))

    summary = {
        "workflow": "servicenow_emergency_change_approval",
        "expected_outcome": "BLOCKED",
        "actual_outcome": trace.outcome.value,
        "request_id": trace.request_id,
        "decision_id": trace.decision_id,
    }
    _write_json(ARTIFACTS / "summary.json", summary)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    run()
