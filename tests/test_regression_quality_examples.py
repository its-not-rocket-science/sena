from __future__ import annotations

import json

from sena.audit.chain import append_audit_record, compute_chain_hash, verify_audit_chain
from sena.core.models import ActionProposal
from sena.engine.evaluator import PolicyEvaluator
from sena.integrations.approval import (
    ApprovalConnectorBase,
    ApprovalConnectorConfig,
    ApprovalEventRoute,
    InMemoryDeliveryIdempotencyStore,
    build_normalized_approval_event,
)
from sena.integrations.base import DecisionPayload, IntegrationError
from sena.policy.parser import load_policy_bundle


class _TestIntegrationError(IntegrationError):
    pass


class _AllowVerifier:
    def verify(self, *, headers: dict[str, str], raw_body: bytes) -> None:
        del headers, raw_body


class _DemoConnector(ApprovalConnectorBase):
    name = "demo"
    source_system = "demo"
    error_cls = _TestIntegrationError
    invalid_envelope_message = "invalid demo envelope"

    def __init__(self) -> None:
        route = ApprovalEventRoute(
            action_type="approve_vendor_payment",
            actor_id_path="actor.id",
            attributes={"amount": "amount"},
        )
        super().__init__(
            config=ApprovalConnectorConfig(routes={"demo.requested": route}),
            verifier=_AllowVerifier(),
            idempotency_store=InMemoryDeliveryIdempotencyStore(),
        )

    def extract_event_type(self, payload: dict[str, object]) -> str:
        return str(payload["event_type"])

    def compute_delivery_id(self, *, headers, payload, event_type, route) -> str:
        del route
        return str(
            headers.get("x-request-id") or f"{event_type}:{payload['request_id']}"
        )

    def build_normalized_event(self, *, payload, event_type, route, delivery_id):
        return build_normalized_approval_event(
            payload=payload,
            route=route,
            source_event_type=event_type,
            idempotency_key=delivery_id,
            source_system="demo",
            default_request_id=str(payload["request_id"]),
            default_source_record_id=str(payload.get("record_id") or "unknown"),
            error_cls=_TestIntegrationError,
            default_source_object_type="demo_object",
            default_workflow_stage="requested",
            default_requested_action=route.action_type,
            default_correlation_key=str(payload["request_id"]),
        )

    def send_decision(self, payload: DecisionPayload) -> dict[str, object]:
        return {"status": "ok", "decision_id": payload.decision_id}


def test_evaluator_deterministic_for_semantically_equivalent_input_ordering() -> None:
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    evaluator = PolicyEvaluator(rules, policy_bundle=metadata)

    proposal_a = ActionProposal(
        action_type="approve_vendor_payment",
        actor_id="u-1",
        actor_role="finance_analyst",
        request_id="req-1",
        attributes={"amount": 10_000, "vendor_verified": True, "source_system": "jira"},
    )
    proposal_b = ActionProposal(
        action_type="approve_vendor_payment",
        actor_id="u-1",
        actor_role="finance_analyst",
        request_id="req-1",
        attributes={"source_system": "jira", "vendor_verified": True, "amount": 10_000},
    )

    first = evaluator.evaluate(proposal_a, {"geo": "us", "risk_score": 2})
    second = evaluator.evaluate(proposal_b, {"risk_score": 2, "geo": "us"})

    assert first.outcome == second.outcome
    assert first.decision_hash == second.decision_hash
    assert first.audit_record is not None and second.audit_record is not None
    assert first.audit_record.input_fingerprint == second.audit_record.input_fingerprint


def test_evaluator_canonical_payload_is_replay_stable() -> None:
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    evaluator = PolicyEvaluator(rules, policy_bundle=metadata)
    proposal = ActionProposal(
        action_type="approve_vendor_payment",
        actor_id="u-1",
        actor_role="finance_analyst",
        request_id="req-canonical",
        attributes={"amount": 10_000, "vendor_verified": True, "source_system": "jira"},
    )
    facts = {"geo": "us", "risk_score": 2}

    first = evaluator.evaluate(proposal, facts)
    second = evaluator.evaluate(proposal, facts)

    assert first.canonical_replay_payload == second.canonical_replay_payload
    assert first.audit_record is not None and second.audit_record is not None
    assert (
        first.audit_record.canonical_replay_payload
        == second.audit_record.canonical_replay_payload
    )


def test_audit_verification_detects_sequence_reuse_even_with_recomputed_hash(
    tmp_path,
) -> None:
    sink = tmp_path / "audit.jsonl"
    append_audit_record(str(sink), {"decision_id": "dec-1", "outcome": "APPROVED"})
    append_audit_record(str(sink), {"decision_id": "dec-2", "outcome": "BLOCKED"})

    rows = [json.loads(line) for line in sink.read_text(encoding="utf-8").splitlines()]
    first, second = rows
    second["storage_sequence_number"] = first["storage_sequence_number"]

    body_for_hash = {k: v for k, v in second.items() if k != "chain_hash"}
    second["chain_hash"] = compute_chain_hash(body_for_hash, second["previous_chain_hash"])
    sink.write_text(
        "\n".join(json.dumps(row) for row in [first, second]) + "\n",
        encoding="utf-8",
    )

    verification = verify_audit_chain(str(sink))
    assert verification["valid"] is False
    assert any(
        "duplicate storage sequence number" in err for err in verification["errors"]
    )


def test_integration_normalization_is_idempotent_for_duplicate_delivery_ids() -> None:
    connector = _DemoConnector()
    event = {
        "headers": {"X-Request-Id": "delivery-1"},
        "payload": {
            "event_type": "demo.requested",
            "request_id": "REQ-1",
            "record_id": "100",
            "actor": {"id": "alice"},
            "amount": 700,
        },
        "raw_body": b"{}",
    }

    first = connector.handle_event(event)
    assert first["normalized_event"]["idempotency_key"] == "delivery-1"

    try:
        connector.handle_event(event)
    except _TestIntegrationError as exc:
        assert "duplicate delivery" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected duplicate delivery to be rejected")


def test_normalized_event_canonical_payload_is_timestamp_stable() -> None:
    route = ApprovalEventRoute(
        action_type="approve_vendor_payment",
        actor_id_path="actor.id",
        attributes={"amount": "amount"},
    )
    payload = {
        "actor": {"id": "alice"},
        "amount": 700,
    }
    first = build_normalized_approval_event(
        payload=payload,
        route=route,
        source_event_type="demo.requested",
        idempotency_key="delivery-1",
        source_system="demo",
        default_request_id="REQ-1",
        default_source_record_id="100",
        error_cls=_TestIntegrationError,
        default_source_object_type="demo_object",
        default_workflow_stage="requested",
        default_requested_action=route.action_type,
        default_correlation_key="REQ-1",
    )
    second = build_normalized_approval_event(
        payload=payload,
        route=route,
        source_event_type="demo.requested",
        idempotency_key="delivery-1",
        source_system="demo",
        default_request_id="REQ-1",
        default_source_record_id="100",
        error_cls=_TestIntegrationError,
        default_source_object_type="demo_object",
        default_workflow_stage="requested",
        default_requested_action=route.action_type,
        default_correlation_key="REQ-1",
    )

    assert first.event_timestamp != second.event_timestamp
    assert first.canonical_replay_payload() == second.canonical_replay_payload()
