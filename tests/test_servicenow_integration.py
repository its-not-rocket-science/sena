import json
from pathlib import Path

import pytest

from sena.integrations.base import DecisionPayload
from sena.integrations.servicenow import (
    ServiceNowConnector,
    ServiceNowIntegrationError,
    load_servicenow_mapping_config,
)


def _fixture(name: str) -> dict:
    fixture_path = Path("tests/fixtures/integrations/servicenow") / f"{name}.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def test_load_servicenow_mapping_config() -> None:
    cfg = load_servicenow_mapping_config(
        "src/sena/examples/integrations/servicenow_mappings.yaml"
    )
    assert "change_approval.requested" in cfg.routes
    assert cfg.outbound.mode == "callback"


@pytest.mark.parametrize(
    "fixture_name,expected_flags",
    [
        ("emergency_change", (True, False, True)),
        ("privileged_change", (False, True, False)),
        ("out_of_hours_change", (False, False, True)),
        ("missing_approver_chain", (False, False, False)),
        ("missing_cab_review_evidence", (False, True, False)),
    ],
)
def test_servicenow_connector_maps_change_approval_examples(
    fixture_name: str,
    expected_flags: tuple[bool, bool, bool],
) -> None:
    cfg = load_servicenow_mapping_config(
        "src/sena/examples/integrations/servicenow_mappings.yaml"
    )
    connector = ServiceNowConnector(config=cfg)
    payload = _fixture(fixture_name)

    event = connector.handle_event(
        {
            "headers": {"x-servicenow-delivery-id": f"delivery-{fixture_name}"},
            "payload": payload,
            "raw_body": json.dumps(payload).encode("utf-8"),
        }
    )

    proposal = event["action_proposal"]
    assert proposal.action_type == "approve_vendor_payment"
    assert proposal.request_id == payload["change_request"]["number"]
    assert proposal.attributes["emergency_change"] is expected_flags[0]
    assert proposal.attributes["privileged_change"] is expected_flags[1]
    assert proposal.attributes["out_of_hours_change"] is expected_flags[2]


def test_servicenow_connector_duplicate_delivery_is_replay_safe() -> None:
    cfg = load_servicenow_mapping_config(
        "src/sena/examples/integrations/servicenow_mappings.yaml"
    )
    connector = ServiceNowConnector(config=cfg)
    payload = _fixture("emergency_change")
    envelope = {
        "headers": {"x-servicenow-delivery-id": "delivery-dup"},
        "payload": payload,
        "raw_body": json.dumps(payload).encode("utf-8"),
    }

    connector.handle_event(envelope)
    with pytest.raises(ServiceNowIntegrationError, match="duplicate delivery"):
        connector.handle_event(envelope)


def test_servicenow_connector_returns_stable_error_for_mapping_mismatch() -> None:
    cfg = load_servicenow_mapping_config(
        "src/sena/examples/integrations/servicenow_mappings.yaml"
    )
    connector = ServiceNowConnector(config=cfg)
    payload = _fixture("missing_approver_chain")
    del payload["requested_by"]["user_id"]

    with pytest.raises(ServiceNowIntegrationError, match="missing required fields"):
        connector.handle_event(
            {
                "headers": {"x-servicenow-delivery-id": "delivery-missing"},
                "payload": payload,
                "raw_body": json.dumps(payload).encode("utf-8"),
            }
        )


def test_servicenow_round_trip_source_payload_to_normalized_to_action_proposal() -> (
    None
):
    cfg = load_servicenow_mapping_config(
        "src/sena/examples/integrations/servicenow_mappings.yaml"
    )
    connector = ServiceNowConnector(config=cfg)
    payload = _fixture("emergency_change")

    event = connector.handle_event(
        {
            "headers": {"x-servicenow-delivery-id": "delivery-roundtrip-sn"},
            "payload": payload,
            "raw_body": json.dumps(payload).encode("utf-8"),
        }
    )

    normalized = event["normalized_event"]
    proposal = event["action_proposal"]
    assert normalized["source_system"] == "servicenow"
    assert normalized["source_object_type"] == "change_request"
    assert normalized["workflow_stage"] == "requested"
    assert normalized["requested_action"] == "approve_vendor_payment"
    assert normalized["actor"]["actor_role"] == payload["requested_by"]["role"]
    assert (
        proposal.attributes["risk_attributes"]["risk_level"] == payload["risk"]["level"]
    )
    assert proposal.attributes["evidence_references"]


def test_servicenow_connector_rejects_missing_required_normalized_fields() -> None:
    cfg = load_servicenow_mapping_config(
        "src/sena/examples/integrations/servicenow_mappings.yaml"
    )
    broken_route = cfg.routes["change_approval.requested"]
    cfg.routes["change_approval.requested"] = broken_route.__class__(
        **{
            **broken_route.__dict__,
            "correlation_key_path": "change_request.missing_number",
        }
    )
    connector = ServiceNowConnector(config=cfg)

    payload = _fixture("emergency_change")
    with pytest.raises(ServiceNowIntegrationError, match="missing required field path"):
        connector.handle_event(
            {
                "headers": {"x-servicenow-delivery-id": "delivery-bad-normalized-sn"},
                "payload": payload,
                "raw_body": json.dumps(payload).encode("utf-8"),
            }
        )


def test_servicenow_send_decision_returns_deterministic_callback_shape() -> None:
    cfg = load_servicenow_mapping_config(
        "src/sena/examples/integrations/servicenow_mappings.yaml"
    )
    connector = ServiceNowConnector(config=cfg)

    response = connector.send_decision(
        DecisionPayload(
            decision_id="dec_sn_1",
            request_id="CHG0091005",
            action_type="approve_vendor_payment",
            matched_rule_ids=["RULE-1", "RULE-2"],
            summary="BLOCKED",
        )
    )
    assert response["status"] == "delivered"
    assert response["payload"]["source_system"] == "servicenow"
    assert response["payload"]["deterministic"] is True


def test_servicenow_send_decision_is_idempotent_for_duplicate_retry() -> None:
    cfg = load_servicenow_mapping_config(
        "src/sena/examples/integrations/servicenow_mappings.yaml"
    )
    connector = ServiceNowConnector(config=cfg)
    payload = DecisionPayload(
        decision_id="dec_sn_dupe",
        request_id="CHG0092001",
        action_type="approve_vendor_payment",
        matched_rule_ids=["RULE-1"],
        summary="ALLOWED",
    )
    first = connector.send_decision(payload)
    second = connector.send_decision(payload)
    assert first["status"] == "delivered"
    assert second["delivery"]["status"] == "duplicate_suppressed"


def test_servicenow_send_decision_writes_dlq_after_retry_exhaustion() -> None:
    class _FailingCallbackClient:
        def publish_callback(self, payload: dict) -> dict:
            del payload
            raise RuntimeError("callback timeout")

    cfg = load_servicenow_mapping_config(
        "src/sena/examples/integrations/servicenow_mappings.yaml"
    )
    connector = ServiceNowConnector(config=cfg, delivery_client=_FailingCallbackClient())
    response = connector.send_decision(
        DecisionPayload(
            decision_id="dec_sn_fail",
            request_id="CHG0092002",
            action_type="approve_vendor_payment",
            matched_rule_ids=["RULE-1"],
            summary="BLOCKED",
        )
    )
    assert response["status"] == "delivery_failed"
    assert len(connector.dead_letter_items()) == 1
