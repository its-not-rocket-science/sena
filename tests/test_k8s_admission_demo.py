from __future__ import annotations

import json
import importlib
import sys
from pathlib import Path

DEMO_DIR = Path("examples/k8s_admission_demo").resolve()
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))

ai_agent_simulator = importlib.import_module("ai_agent_simulator")
sena_webhook = importlib.import_module("sena_webhook")


def test_ai_agent_simulator_extracts_replica_count() -> None:
    replicas = ai_agent_simulator._extract_replicas("Please increase replicas to 10")
    assert replicas == 10


def test_webhook_returns_blocked_with_proof_annotation(monkeypatch) -> None:
    review = {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "request": {
            "uid": "uid-1",
            "userInfo": {"username": "ai-agent"},
            "object": {
                "metadata": {
                    "name": "payments-api",
                    "namespace": "production",
                    "annotations": {"demo.sena.current_replicas": "3"},
                },
                "spec": {"replicas": 10},
            },
        },
    }

    monkeypatch.setattr(
        sena_webhook,
        "_call_sena_api",
        lambda payload: {
            "decision": "BLOCKED",
            "summary": "Blocked by budget cap.",
            "audit_record": {"decision_id": "d-1"},
        },
    )
    monkeypatch.setattr(
        sena_webhook,
        "_proof_for_decision",
        lambda decision_id: {
            "decision_id": decision_id,
            "record_index": 0,
            "merkle_root": "root",
            "merkle_proof": ["leaf"],
        },
    )

    response = sena_webhook.evaluate_admission_review(review)
    assert response["response"]["allowed"] is False
    assert "sena.audit.proof" in response["response"]["auditAnnotations"]

    proof = json.loads(response["response"]["auditAnnotations"]["sena.audit.proof"])
    assert proof["decision_id"] == "d-1"
