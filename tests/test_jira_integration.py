import json

import pytest

from sena.integrations.base import DecisionPayload
from sena.integrations.jira import (
    AllowAllJiraWebhookVerifier,
    JiraConnector,
    JiraIntegrationError,
    SharedSecretJiraWebhookVerifier,
    load_jira_mapping_config,
)


def _payload(actor: str = "acct-1") -> dict:
    return {
        "webhookEvent": "jira:issue_updated",
        "timestamp": 1711982000,
        "issue": {
            "id": "10001",
            "key": "RISK-9",
            "fields": {
                "customfield_approval_amount": 12000,
                "customfield_requester_role": "finance_analyst",
                "customfield_vendor_verified": False,
            },
        },
        "user": {"accountId": actor},
        "changelog": {"items": [{"field": "status", "toString": "Pending Approval"}]},
    }


def test_load_jira_mapping_config() -> None:
    cfg = load_jira_mapping_config("src/sena/examples/integrations/jira_mappings.yaml")
    assert "jira:issue_updated" in cfg.routes
    assert cfg.outbound.mode == "both"


def test_jira_connector_maps_payload_to_action_proposal() -> None:
    cfg = load_jira_mapping_config("src/sena/examples/integrations/jira_mappings.yaml")
    connector = JiraConnector(config=cfg, verifier=AllowAllJiraWebhookVerifier())

    event = connector.handle_event(
        {
            "headers": {"x-atlassian-webhook-identifier": "delivery-1"},
            "payload": _payload(),
            "raw_body": json.dumps(_payload()).encode("utf-8"),
        }
    )

    proposal = event["action_proposal"]
    assert proposal.action_type == "approve_vendor_payment"
    assert proposal.request_id == "RISK-9"
    assert proposal.actor_id == "acct-1"
    assert proposal.attributes["amount"] == 12000


def test_jira_connector_missing_actor_identity_is_deterministic() -> None:
    cfg = load_jira_mapping_config("src/sena/examples/integrations/jira_mappings.yaml")
    connector = JiraConnector(config=cfg, verifier=AllowAllJiraWebhookVerifier())

    payload = _payload(actor="")
    with pytest.raises(JiraIntegrationError, match="missing actor identity"):
        connector.handle_event(
            {
                "headers": {"x-atlassian-webhook-identifier": "delivery-2"},
                "payload": payload,
                "raw_body": json.dumps(payload).encode("utf-8"),
            }
        )


def test_jira_connector_duplicate_delivery_is_replay_safe() -> None:
    cfg = load_jira_mapping_config("src/sena/examples/integrations/jira_mappings.yaml")
    connector = JiraConnector(config=cfg, verifier=AllowAllJiraWebhookVerifier())
    payload = _payload()
    envelope = {
        "headers": {"x-atlassian-webhook-identifier": "delivery-3"},
        "payload": payload,
        "raw_body": json.dumps(payload).encode("utf-8"),
    }

    connector.handle_event(envelope)
    with pytest.raises(JiraIntegrationError, match="duplicate delivery"):
        connector.handle_event(envelope)


def test_jira_verifier_rejects_invalid_signature() -> None:
    cfg = load_jira_mapping_config("src/sena/examples/integrations/jira_mappings.yaml")
    connector = JiraConnector(
        config=cfg,
        verifier=SharedSecretJiraWebhookVerifier("topsecret"),
    )
    payload = _payload()
    with pytest.raises(JiraIntegrationError, match="invalid webhook signature"):
        connector.handle_event(
            {
                "headers": {
                    "x-atlassian-webhook-identifier": "delivery-4",
                    "x-sena-signature": "bad",
                },
                "payload": payload,
                "raw_body": json.dumps(payload).encode("utf-8"),
            }
        )


def test_jira_round_trip_source_payload_to_normalized_to_action_proposal() -> None:
    cfg = load_jira_mapping_config("src/sena/examples/integrations/jira_mappings.yaml")
    connector = JiraConnector(config=cfg, verifier=AllowAllJiraWebhookVerifier())
    payload = _payload()

    event = connector.handle_event(
        {
            "headers": {"x-atlassian-webhook-identifier": "delivery-roundtrip"},
            "payload": payload,
            "raw_body": json.dumps(payload).encode("utf-8"),
        }
    )

    normalized = event["normalized_event"]
    proposal = event["action_proposal"]
    assert normalized["source_system"] == "jira"
    assert normalized["source_object_type"] == "jira_issue"
    assert normalized["source_object_id"] == "10001"
    assert normalized["workflow_stage"] == "pending_approval"
    assert normalized["requested_action"] == "approve_vendor_payment"
    assert normalized["actor"]["actor_id"] == "acct-1"
    assert proposal.request_id == "RISK-9"
    assert proposal.attributes["correlation_key"] == "RISK-9"


def test_jira_connector_rejects_missing_required_normalized_fields() -> None:
    cfg = load_jira_mapping_config("src/sena/examples/integrations/jira_mappings.yaml")
    broken_route = cfg.routes["jira:issue_updated"]
    cfg.routes["jira:issue_updated"] = broken_route.__class__(
        **{**broken_route.__dict__, "correlation_key_path": "issue.missing_key"}
    )
    connector = JiraConnector(config=cfg, verifier=AllowAllJiraWebhookVerifier())

    payload = _payload()
    with pytest.raises(JiraIntegrationError, match="missing required field path"):
        connector.handle_event(
            {
                "headers": {
                    "x-atlassian-webhook-identifier": "delivery-bad-normalized"
                },
                "payload": payload,
                "raw_body": json.dumps(payload).encode("utf-8"),
            }
        )


def test_jira_send_decision_returns_stable_payload() -> None:
    cfg = load_jira_mapping_config("src/sena/examples/integrations/jira_mappings.yaml")
    connector = JiraConnector(config=cfg, verifier=AllowAllJiraWebhookVerifier())
    response = connector.send_decision(
        DecisionPayload(
            decision_id="dec_1",
            request_id="RISK-10",
            action_type="approve_vendor_payment",
            matched_rule_ids=["RULE-1"],
            summary="BLOCKED",
        )
    )
    assert response["status"] == "delivered"
    assert len(response["results"]) == 2
