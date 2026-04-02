from __future__ import annotations

import json
import re
from pathlib import Path

from sena.core.enums import DecisionOutcome
from sena.core.models import ActionProposal, EvaluationTrace
from sena.engine.evaluator import PolicyEvaluator
from sena.engine.review_package import build_decision_review_package
from sena.policy.parser import load_policy_bundle


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _normalize(package: dict) -> dict:
    normalized = json.loads(json.dumps(package))
    normalized["package_generated_at"] = "<timestamp>"
    normalized["decision_summary"]["decision_id"] = "<decision_id>"
    normalized["decision_summary"]["decision_timestamp"] = "<timestamp>"
    normalized["audit_identifiers"]["decision_hash"] = "<decision_hash>"
    normalized["audit_identifiers"]["input_fingerprint"] = "<input_fingerprint>"
    normalized["decision_summary"]["summary"] = re.sub(
        r"dec_[a-f0-9]+", "<decision_id>", normalized["decision_summary"]["summary"]
    )
    return normalized


def _evaluator() -> PolicyEvaluator:
    rules, metadata = load_policy_bundle(
        "src/sena/examples/policies",
        bundle_name="enterprise-demo",
        version="2026.03",
    )
    return PolicyEvaluator(rules, policy_bundle=metadata)


def test_review_package_snapshot_for_blocked_decision() -> None:
    evaluator = _evaluator()
    trace = evaluator.evaluate(
        ActionProposal(
            action_type="approve_vendor_payment",
            request_id="req-review-block",
            actor_id="actor-1",
            actor_role="finance_analyst",
            attributes={
                "amount": 15000,
                "vendor_verified": False,
                "requester_role": "finance_analyst",
            },
        ),
        facts={},
    )

    assert trace.outcome == DecisionOutcome.BLOCKED
    package = build_decision_review_package(trace)
    assert _normalize(package) == _load_json(
        "tests/fixtures/golden/review_packages/blocked_vendor_payment.json"
    )


def test_review_package_snapshot_for_escalation_decision() -> None:
    evaluator = _evaluator()
    trace = evaluator.evaluate(
        ActionProposal(
            action_type="export_customer_data",
            request_id="req-review-escalate",
            actor_id="actor-2",
            actor_role="privacy_analyst",
            attributes={"requested_fields": ["date_of_birth"], "dpo_approved": False},
        ),
        facts={},
    )

    assert trace.outcome == DecisionOutcome.ESCALATE_FOR_HUMAN_REVIEW
    package = build_decision_review_package(trace)
    assert _normalize(package) == _load_json(
        "tests/fixtures/golden/review_packages/escalated_export.json"
    )


def test_review_package_handles_missing_optional_fields() -> None:
    package = build_decision_review_package(
        EvaluationTrace(
            action_type="stub",
            outcome=DecisionOutcome.APPROVED,
            summary="stub summary",
            decision_id="dec_stub",
        )
    )

    assert package["policy_bundle_metadata"]["bundle_name"] is None
    assert package["normalized_source_system_references"] == []
    assert package["precedence"]["explanation"] is None
    assert package["governance_evidence"]["missing_evidence_classes"] == []
