from __future__ import annotations

import json
from pathlib import Path

import pytest

from sena.core.enums import RuleDecision, Severity
from sena.core.models import PolicyRule
from sena.integrations.approval import (
    ApprovalEventRoute,
    build_normalized_approval_event,
)
from sena.integrations.base import IntegrationError
from sena.policy.lifecycle import diff_rule_sets, validate_promotion


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _normalize_error(body: dict) -> dict:
    normalized = json.loads(json.dumps(body))
    normalized["error"]["timestamp"] = "<timestamp>"
    return normalized


def test_golden_api_error_envelopes() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from sena.api.app import create_app
    from sena.api.config import ApiSettings

    app = create_app(
        ApiSettings(
            policy_dir="src/sena/examples/policies",
            bundle_name="enterprise-demo",
            bundle_version="2026.03",
            enable_api_key_auth=True,
            api_key="secret",
            api_keys=(),
            request_max_bytes=1_048_576,
            request_timeout_seconds=15.0,
        )
    )
    client = TestClient(app)

    invalid_length = client.post(
        "/v1/evaluate",
        headers={
            "content-length": "nan",
            "x-api-key": "secret",
            "x-request-id": "req-golden",
        },
        content=b"{}",
    )
    assert invalid_length.status_code == 400
    assert _normalize_error(invalid_length.json()) == _load_json(
        "tests/fixtures/golden/api/invalid_content_length.json"
    )

    unauthorized = client.post(
        "/v1/evaluate",
        headers={"x-request-id": "req-golden"},
        json={"action_type": "approve_vendor_payment"},
    )
    assert unauthorized.status_code == 401
    assert _normalize_error(unauthorized.json()) == _load_json(
        "tests/fixtures/golden/api/unauthorized.json"
    )


def test_golden_bundle_diff_and_promotion_validation_results() -> None:
    source = [
        PolicyRule(
            id="stable_allow",
            description="allow",
            severity=Severity.LOW,
            inviolable=False,
            applies_to=["act"],
            condition={"field": "amount", "lt": 10},
            decision=RuleDecision.ALLOW,
            reason="allow",
        )
    ]
    target = [
        PolicyRule(
            id="stable_allow",
            description="allow changed",
            severity=Severity.LOW,
            inviolable=False,
            applies_to=["act"],
            condition={"field": "amount", "lt": 10},
            decision=RuleDecision.ALLOW,
            reason="allow",
        ),
        PolicyRule(
            id="new_block",
            description="new block",
            severity=Severity.HIGH,
            inviolable=True,
            applies_to=["act"],
            condition={"field": "amount", "gte": 10},
            decision=RuleDecision.BLOCK,
            reason="block",
        ),
    ]

    diff = diff_rule_sets(source, target)
    assert diff.__dict__ == _load_json("tests/fixtures/golden/bundles/diff_result.json")

    invalid_target = [
        PolicyRule(
            id="dup",
            description="allow",
            severity=Severity.LOW,
            inviolable=False,
            applies_to=["act"],
            condition={"field": "amount", "lt": 10},
            decision=RuleDecision.ALLOW,
            reason="allow",
        ),
        PolicyRule(
            id="dup",
            description="allow",
            severity=Severity.LOW,
            inviolable=False,
            applies_to=["act"],
            condition={"field": "amount", "lt": 10},
            decision=RuleDecision.ALLOW,
            reason="allow",
        ),
    ]
    promotion = validate_promotion(
        "candidate", "active", [], invalid_target, validation_artifact=None
    )
    assert promotion.__dict__ == _load_json(
        "tests/fixtures/golden/bundles/promotion_validation.json"
    )


def test_golden_normalized_integration_payload() -> None:
    route = ApprovalEventRoute(
        action_type="approve_vendor_payment",
        actor_id_path="requester.id",
        actor_role_path="requester.role",
        request_id_path="request.id",
        source_record_id_path="ticket.id",
        correlation_key_path="ticket.id",
        attributes={"amount": "payment.amount", "currency": "payment.currency"},
        risk_attributes={"risk_score": "risk.score"},
        evidence_references_path="evidence",
    )
    payload = {
        "requester": {"id": "user-1", "role": "analyst"},
        "request": {"id": "REQ-1"},
        "ticket": {"id": "T-100"},
        "payment": {"amount": 75, "currency": "USD"},
        "risk": {"score": 80},
        "evidence": ["doc-1", "doc-2"],
    }

    normalized = build_normalized_approval_event(
        payload=payload,
        route=route,
        source_event_type="approval.requested",
        idempotency_key="idem-1",
        source_system="partner",
        default_request_id="fallback-req",
        default_source_record_id="fallback-src",
        error_cls=IntegrationError,
        source_metadata={"source_delivery_id": "delivery-9"},
        default_source_object_type="ticket",
        default_workflow_stage="requested",
        default_requested_action="approve_vendor_payment",
        default_correlation_key="fallback-corr",
    ).model_dump()
    normalized["event_timestamp"] = "<timestamp>"

    assert normalized == _load_json(
        "tests/fixtures/golden/integrations/normalized_approval_event.json"
    )
