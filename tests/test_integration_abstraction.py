from __future__ import annotations

from dataclasses import dataclass

from sena.integrations.approval import (
    ApprovalConnectorBase,
    ApprovalConnectorConfig,
    ApprovalEventRoute,
    InMemoryDeliveryIdempotencyStore,
    MinimalApprovalEventContract,
    build_normalized_approval_event,
)
from sena.integrations.base import DecisionPayload, IntegrationError


class _TestError(IntegrationError):
    pass


class _AllowAllVerifier:
    def verify(self, *, headers: dict[str, str], raw_body: bytes) -> None:
        return None


@dataclass(frozen=True)
class _Config:
    routes: dict[str, ApprovalEventRoute]


class _DemoConnector(ApprovalConnectorBase):
    name = "demo"
    source_system = "demo"
    error_cls = _TestError
    invalid_envelope_message = "invalid demo event envelope"

    def __init__(self) -> None:
        route = ApprovalEventRoute(
            action_type="approve",
            actor_id_path="actor.id",
            attributes={"amount": "amount"},
        )
        super().__init__(
            config=ApprovalConnectorConfig(routes={"demo.requested": route}),
            verifier=_AllowAllVerifier(),
            idempotency_store=InMemoryDeliveryIdempotencyStore(),
        )

    def extract_event_type(self, payload: dict[str, object]) -> str:
        return str(payload["event_type"])

    def compute_delivery_id(self, *, headers, payload, event_type, route) -> str:
        del route
        return str(headers.get("x-request-id") or f"{event_type}:{payload['request_id']}")

    def build_normalized_event(self, *, payload, event_type, route, delivery_id):
        normalized = build_normalized_approval_event(
            payload=payload,
            route=route,
            source_event_type=event_type,
            idempotency_key=delivery_id,
            source_system="demo",
            default_request_id=str(payload["request_id"]),
            default_source_record_id=str(payload["record_id"]),
            error_cls=_TestError,
            default_source_object_type="demo_object",
            default_workflow_stage="requested",
            default_requested_action=route.action_type,
            default_correlation_key=str(payload["request_id"]),
        )
        MinimalApprovalEventContract(
            source_system=normalized.source_system,
            source_event_type=normalized.source_event_type,
            request_id=normalized.request_id,
            requested_action=normalized.requested_action,
            actor_id=normalized.actor.actor_id,
            correlation_key=normalized.correlation_key,
            idempotency_key=normalized.idempotency_key,
        )
        return normalized

    def send_decision(self, payload: DecisionPayload) -> dict[str, object]:
        return {"status": "ok", "decision_id": payload.decision_id}


def test_approval_connector_base_produces_normalized_contract_and_proposal() -> None:
    connector = _DemoConnector()
    response = connector.handle_event(
        {
            "headers": {"x-request-id": "d-1"},
            "payload": {
                "event_type": "demo.requested",
                "request_id": "REQ-1",
                "record_id": "100",
                "actor": {"id": "u-1"},
                "amount": 120,
            },
            "raw_body": b"{}",
        }
    )
    assert response["normalized_event"]["source_system"] == "demo"
    assert "event_timestamp" not in response["canonical_replay_payload"]
    assert "event_timestamp" in response["operational_metadata"]
    assert response["determinism_contract"]["scope"] == "canonical_replay_payload_only"
    assert (
        response["determinism_contract"]["canonical_replay_payload"]
        == response["canonical_replay_payload"]
    )
    assert (
        response["determinism_contract"]["operational_metadata"]
        == response["operational_metadata"]
    )
    assert response["action_proposal"].request_id == "REQ-1"
