from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Any

from sena.audit.merkle import build_merkle_tree, get_proof
from sena.audit.sinks import JsonlFileAuditSink
from sena.core.enums import ActionOrigin, DecisionOutcome
from sena.core.models import AIActionMetadata, ActionProposal, EvaluatorConfig, RiskClassification
from sena.engine.evaluator import PolicyEvaluator
from sena.policy.parser import load_policy_bundle
from sena.services.audit_service import AuditService

try:
    from fastapi import FastAPI
except ModuleNotFoundError:  # pragma: no cover
    FastAPI = None  # type: ignore

SENA_API_URL = os.getenv("SENA_API_URL", "http://localhost:8000")
SENA_AUDIT_PATH = os.getenv(
    "SENA_AUDIT_PATH", "examples/k8s_admission_demo/artifacts/audit/demo_audit.jsonl"
)
SENA_POLICY_DIR = os.getenv("SENA_POLICY_DIR", "examples/k8s_admission_demo/policies")


def _build_sena_request(admission_review: dict[str, Any]) -> dict[str, Any]:
    request_obj = admission_review["request"]
    deployment = request_obj["object"]
    spec = deployment.get("spec", {})
    metadata = deployment.get("metadata", {})
    annotations = metadata.get("annotations", {})
    ai_source = annotations.get("demo.sena.ai/source", "ai-agent-simulator")
    current_replicas = int(annotations.get("demo.sena.current_replicas", "3"))
    proposed_replicas = int(spec.get("replicas", 1))

    return {
        "action_type": "k8s_update_deployment",
        "request_id": request_obj.get("uid"),
        "actor_id": request_obj.get("userInfo", {}).get("username", "ai-agent"),
        "actor_role": "k8s_workload_optimizer",
        "action_origin": "ai_suggested",
        "attributes": {
            "deployment_name": metadata.get("name"),
            "namespace": metadata.get("namespace"),
            "current_replicas": current_replicas,
            "proposed_replicas": proposed_replicas,
        },
        "ai_metadata": {
            "originating_system": ai_source,
            "originating_model": annotations.get("demo.sena.ai/model", "simulated"),
            "prompt_context_ref": "k8s-admission-demo/high-traffic",
            "confidence": 0.78,
            "uncertainty": "medium",
            "requested_tool": "kubectl",
            "requested_action": "scale deployment",
            "evidence_references": ["incident/high-traffic-drill-01"],
            "citation_references": [],
            "human_requester": "traffic-monitor",
            "human_owner": "platform-owner",
            "human_approver": None,
            "risk_classification": {
                "category": "cost-control",
                "level": "high",
                "tags": ["kubernetes", "autoscaling", "budget"],
                "rationale": "Scaling above 5 replicas can exceed demo cost envelope.",
            },
        },
        "facts": {},
        "default_decision": "APPROVED",
    }


def _call_sena_api(payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{SENA_API_URL}/v1/evaluate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _evaluate_locally(payload: dict[str, Any]) -> dict[str, Any]:
    rules, metadata = load_policy_bundle(SENA_POLICY_DIR)
    evaluator = PolicyEvaluator(
        rules,
        policy_bundle=metadata,
        config=EvaluatorConfig(default_decision=DecisionOutcome.APPROVED),
    )
    ai_metadata_raw = payload["ai_metadata"]
    proposal = ActionProposal(
        action_type=str(payload["action_type"]),
        request_id=payload.get("request_id"),
        actor_id=payload.get("actor_id"),
        actor_role=payload.get("actor_role"),
        attributes=dict(payload.get("attributes", {})),
        action_origin=ActionOrigin.AI_SUGGESTED,
        ai_metadata=AIActionMetadata(
            originating_system=str(ai_metadata_raw["originating_system"]),
            originating_model=ai_metadata_raw.get("originating_model"),
            prompt_context_ref=ai_metadata_raw.get("prompt_context_ref"),
            confidence=ai_metadata_raw.get("confidence"),
            uncertainty=ai_metadata_raw.get("uncertainty"),
            requested_tool=ai_metadata_raw.get("requested_tool"),
            requested_action=ai_metadata_raw.get("requested_action"),
            evidence_references=list(ai_metadata_raw.get("evidence_references", [])),
            citation_references=list(ai_metadata_raw.get("citation_references", [])),
            human_requester=ai_metadata_raw.get("human_requester"),
            human_owner=ai_metadata_raw.get("human_owner"),
            human_approver=ai_metadata_raw.get("human_approver"),
            risk_classification=RiskClassification(**ai_metadata_raw["risk_classification"]),
        ),
    )
    trace = evaluator.evaluate(proposal, dict(payload.get("facts", {})))
    result = trace.to_dict()
    appended = AuditService(SENA_AUDIT_PATH).append_record(result["audit_record"])
    if appended is not None:
        result["audit_record"] = appended
    return result


def _proof_for_decision(decision_id: str) -> dict[str, Any]:
    sink = JsonlFileAuditSink(path=SENA_AUDIT_PATH)
    records = sink.load_records()
    if not records:
        raise RuntimeError("no audit records found for merkle proof generation")

    index = None
    for i, row in enumerate(records):
        if str(row.get("decision_id")) == decision_id:
            index = i
            break
    if index is None:
        raise RuntimeError("decision_id not found in audit sink")

    tree = build_merkle_tree(records)
    proof = get_proof(tree, index)
    return {
        "decision_id": decision_id,
        "record_index": index,
        "merkle_root": tree.root,
        "merkle_proof": proof,
        "audit_sink": SENA_AUDIT_PATH,
    }


def evaluate_admission_review(admission_review: dict[str, Any]) -> dict[str, Any]:
    uid = admission_review["request"]["uid"]
    sena_request = _build_sena_request(admission_review)
    try:
        sena_result = _call_sena_api(sena_request)
    except urllib.error.URLError:
        sena_result = _evaluate_locally(sena_request)

    raw_decision = sena_result.get("decision", "APPROVED")
    decision = getattr(raw_decision, "value", str(raw_decision))
    allowed = decision == "APPROVED"
    audit_record = sena_result.get("audit_record", {})
    proof_payload = _proof_for_decision(str(audit_record.get("decision_id", "")))
    proof_json = json.dumps(proof_payload, sort_keys=True)

    status_message = (
        "SENA blocked AI-suggested scale change: max replicas = 5."
        if not allowed
        else "SENA approved deployment change."
    )
    admission_response = {
        "uid": uid,
        "allowed": allowed,
        "status": {"message": status_message},
        "auditAnnotations": {
            "sena.decision": decision,
            "sena.summary": str(sena_result.get("summary", "")),
            "sena.audit.proof": proof_json,
            "sena.audit.proof.b64": base64.b64encode(proof_json.encode("utf-8")).decode(
                "utf-8"
            ),
        },
    }
    return {
        "apiVersion": admission_review.get("apiVersion", "admission.k8s.io/v1"),
        "kind": "AdmissionReview",
        "response": admission_response,
        "sena_result": sena_result,
    }


if FastAPI is not None:
    app = FastAPI(title="SENA K8s Admission Webhook", version="0.1.0")

    @app.post("/admission/review")
    def admission_review(payload: dict[str, Any]) -> dict[str, Any]:
        return evaluate_admission_review(payload)
