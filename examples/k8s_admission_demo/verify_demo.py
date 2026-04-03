from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from sena.audit.merkle import verify_proof
from sena.audit.sinks import JsonlFileAuditSink

from ai_agent_simulator import suggest_change
from sena_webhook import evaluate_admission_review

ARTIFACT_DIR = Path("examples/k8s_admission_demo/artifacts")
AUDIT_PATH = ARTIFACT_DIR / "audit" / "demo_audit.jsonl"


def _seed_environment() -> None:
    (ARTIFACT_DIR / "audit").mkdir(parents=True, exist_ok=True)
    if not AUDIT_PATH.exists():
        AUDIT_PATH.touch()
    os.environ.setdefault("SENA_AUDIT_PATH", str(AUDIT_PATH))


def build_admission_review(change: dict[str, Any]) -> dict[str, Any]:
    return {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "request": {
            "uid": "demo-admission-001",
            "operation": "UPDATE",
            "userInfo": {"username": "ai-agent"},
            "object": {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {
                    "name": change["deployment_name"],
                    "namespace": change["namespace"],
                    "annotations": {
                        "demo.sena.ai/source": "ai_agent_simulator",
                        "demo.sena.ai/model": os.getenv(
                            "OPENAI_MODEL", "simulated-default"
                        ),
                        "demo.sena.current_replicas": str(change["current_replicas"]),
                    },
                },
                "spec": {"replicas": change["proposed_replicas"]},
            },
        },
    }


def extract_proof(admission_response: dict[str, Any]) -> dict[str, Any]:
    annotations = admission_response["response"]["auditAnnotations"]
    return json.loads(annotations["sena.audit.proof"])


def verify_proof_independently(proof_payload: dict[str, Any]) -> bool:
    sink = JsonlFileAuditSink(path=str(AUDIT_PATH))
    records = sink.load_records()
    record = records[int(proof_payload["record_index"])]
    return verify_proof(
        record,
        list(proof_payload["merkle_proof"]),
        str(proof_payload["merkle_root"]),
    )


def _tamper_with_payload(proof_payload: dict[str, Any]) -> dict[str, Any]:
    tampered = deepcopy(proof_payload)
    tampered["merkle_root"] = f"bad{tampered['merkle_root'][3:]}"
    return tampered


def run_demo() -> int:
    _seed_environment()
    print("\n=== STEP 1: AI suggests a Kubernetes change ===")
    suggestion = suggest_change()
    print(json.dumps(suggestion.as_dict(), indent=2))

    print("\n=== STEP 2: SENA admission webhook evaluates the AI suggestion ===")
    admission_review = build_admission_review(suggestion.as_dict())
    response = evaluate_admission_review(admission_review)
    print(json.dumps(response["response"], indent=2))

    allowed = bool(response["response"]["allowed"])
    if allowed:
        print("\nUnexpected approval for investor demo; expected BLOCKED for >5 replicas.")
        return 1

    print("\n=== STEP 3: External auditor verifies the Merkle proof ===")
    proof_payload = extract_proof(response)
    verified = verify_proof_independently(proof_payload)
    print(f"Proof verified: {verified}")
    if not verified:
        return 1

    print("\n=== STEP 4: Tampering attempt fails verification ===")
    tampered = _tamper_with_payload(proof_payload)
    tampered_valid = verify_proof_independently(tampered)
    print(f"Tampered proof verified: {tampered_valid}")
    if tampered_valid:
        return 1

    print("\n✅ Investor demo complete: AI change blocked, audit proof verified, tamper rejected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_demo())
