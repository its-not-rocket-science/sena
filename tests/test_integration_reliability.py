from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from sena.integrations.base import DecisionPayload
from sena.integrations.jira import (
    AllowAllJiraWebhookVerifier,
    JiraConnector,
    JiraIntegrationError,
    load_jira_mapping_config,
)
from sena.integrations.servicenow import (
    ServiceNowConnector,
    ServiceNowIntegrationError,
    load_servicenow_mapping_config,
)
from sena.policy.integration_persistence import SQLiteIntegrationReliabilityStore
from sena.services.integration_service import IntegrationService
from sena.services.reliability_service import InMemoryIngestionQueue, ReliabilityService


class _Store:
    def __init__(self) -> None:
        self.events: list[tuple[dict, str]] = []

    def enqueue_dead_letter(self, event: dict, error: str) -> int:
        self.events.append((event, error))
        return len(self.events)


class _FailingConnector:
    def route_for_event_type(self, _event_type: str):
        return None

    def send_decision(self, _payload):
        raise RuntimeError("integration unavailable")


class _Registry:
    def get(self, name: str):
        if name != "jira":
            raise AssertionError("unexpected connector")

        class _Inbound:
            def handle_event(self, _event):
                proposal = SimpleNamespace(
                    request_id="REQ-1",
                    action_type="approve_vendor_payment",
                    actor_id="actor-1",
                    attributes={},
                )
                return {
                    "normalized_event": {"source_event_type": "jira.issue"},
                    "action_proposal": proposal,
                }

        return _Inbound()


class _Eval:
    def evaluate(self, **_kwargs):
        return {
            "decision_id": "d-1",
            "matched_rules": [{"rule_id": "r-1"}],
            "summary": "approved",
        }


def test_jira_graceful_degradation_returns_fallback_and_queues_retry() -> None:
    store = _Store()
    state = SimpleNamespace(
        connector_registry=_Registry(),
        jira_connector=_FailingConnector(),
        processing_store=store,
        reliability_service=ReliabilityService(ingestion_queue=InMemoryIngestionQueue()),
        metadata=SimpleNamespace(bundle_name="enterprise-demo"),
    )
    service = IntegrationService(state=state, evaluation_service=_Eval())

    result = service.handle_jira_event(headers={}, payload={}, raw_body=b"{}")

    assert result["outbound_delivery"]["status"] == "degraded"
    assert result["outbound_delivery"]["fallback_mode"] == "queue_for_retry"
    assert store.events[0][0]["event_type"] == "integration_outbound_retry"


def test_jira_duplicate_suppression_and_outbound_completion_survive_restart(
    tmp_path,
) -> None:
    db_path = tmp_path / "integration_reliability.db"
    cfg = load_jira_mapping_config("src/sena/examples/integrations/jira_mappings.yaml")

    class _Client:
        def __init__(self) -> None:
            self.comment_calls = 0
            self.status_calls = 0

        def publish_comment(self, issue_key: str, message: str) -> dict:
            self.comment_calls += 1
            return {"issue_key": issue_key, "message": message}

        def publish_status(self, issue_key: str, payload: dict) -> dict:
            self.status_calls += 1
            return {"issue_key": issue_key, "payload": payload}

    client = _Client()
    connector = JiraConnector(
        config=cfg,
        verifier=AllowAllJiraWebhookVerifier(),
        reliability_db_path=str(db_path),
        delivery_client=client,
    )
    payload = {
        "webhookEvent": "jira:issue_updated",
        "timestamp": 1711982000,
        "issue": {
            "id": "10001",
            "key": "RISK-9",
            "fields": {
                "customfield_approval_amount": 12000,
                "customfield_requester_role": "finance_analyst",
                "customfield_vendor_verified": False,
                "customfield_tenant_id": "tenant-finance",
                "customfield_workflow_id": "wf-ap-01",
                "customfield_sla_deadline_at": "2026-04-11T00:00:00Z",
                "customfield_escalation_deadline_at": "2026-04-10T18:00:00Z",
                "customfield_business_unit": "finance",
                "status": {"name": "Pending Approval"},
                "previous_status": {"name": "In Review"},
                "priority": {"name": "P2"},
            },
        },
        "user": {"accountId": "acct-1"},
        "changelog": {"items": [{"field": "status", "toString": "Pending Approval"}]},
    }
    envelope = {
        "headers": {"x-atlassian-webhook-identifier": "restart-delivery-1"},
        "payload": payload,
        "raw_body": json.dumps(payload).encode("utf-8"),
    }
    connector.handle_event(envelope)

    after_restart = JiraConnector(
        config=cfg,
        verifier=AllowAllJiraWebhookVerifier(),
        reliability_db_path=str(db_path),
        delivery_client=client,
    )
    with pytest.raises(JiraIntegrationError, match="duplicate delivery"):
        after_restart.handle_event(envelope)

    decision = DecisionPayload(
        decision_id="dec_restart_1",
        request_id="RISK-9",
        action_type="approve_vendor_payment",
        matched_rule_ids=["RULE-1"],
        summary="ALLOWED",
    )
    first = connector.send_decision(decision)
    second = after_restart.send_decision(decision)
    assert first["status"] == "delivered"
    assert all(result["status"] == "duplicate_suppressed" for result in second["results"])
    assert client.comment_calls == 1
    assert client.status_calls == 1

    persisted = SQLiteIntegrationReliabilityStore(str(db_path)).get_completion(
        "dec_restart_1:comment:RISK-9"
    )
    assert persisted is not None
    assert persisted.max_attempts == cfg.outbound.max_attempts
    assert persisted.attempts == 1


def test_servicenow_dlq_retry_metadata_persists_across_restart(tmp_path) -> None:
    db_path = tmp_path / "integration_reliability.db"
    cfg = load_servicenow_mapping_config(
        "src/sena/examples/integrations/servicenow_mappings.yaml"
    )

    class _FailingClient:
        def publish_callback(self, payload: dict) -> dict:
            del payload
            raise RuntimeError("callback timeout")

    connector = ServiceNowConnector(
        config=cfg,
        reliability_db_path=str(db_path),
        delivery_client=_FailingClient(),
    )
    response = connector.send_decision(
        DecisionPayload(
            decision_id="dec_sn_restart_fail",
            request_id="CHG0092002",
            action_type="approve_vendor_payment",
            matched_rule_ids=["RULE-1"],
            summary="BLOCKED",
        )
    )
    assert response["status"] == "delivery_failed"

    after_restart = ServiceNowConnector(config=cfg, reliability_db_path=str(db_path))
    dead_letters = after_restart.dead_letter_items()
    assert len(dead_letters) == 1
    entry = dead_letters[0]
    assert entry["attempts"] == cfg.outbound.max_attempts
    assert entry["max_attempts"] == cfg.outbound.max_attempts
    assert entry["first_failed_at"] is not None
    assert entry["last_failed_at"] is not None

    payload = {
        "event_type": "change_approval.requested",
        "table": "change_request",
        "change_request": {"sys_id": "SYS-1", "number": "CHG0091005"},
        "requested_by": {"user_id": "u-1", "role": "change_manager"},
        "risk": {"level": "high"},
        "classification": "normal",
        "environment": "prod",
        "schedule": {
            "window": "business_hours",
            "start": "2026-04-09T10:00:00Z",
            "end": "2026-04-09T12:00:00Z",
        },
        "flags": {"emergency": False, "privileged": False, "out_of_hours": False},
        "approver_chain": ["u-1"],
        "approver_chain_missing": False,
        "cab_review": {"evidence_id": "CAB-1"},
        "cab_review_missing": False,
        "fixture_version": "1",
    }
    envelope = {
        "headers": {"x-servicenow-delivery-id": "sn-duplicate-1"},
        "payload": payload,
        "raw_body": json.dumps(payload).encode("utf-8"),
    }
    after_restart.handle_event(envelope)
    with pytest.raises(ServiceNowIntegrationError, match="duplicate delivery"):
        ServiceNowConnector(config=cfg, reliability_db_path=str(db_path)).handle_event(
            envelope
        )


def test_supported_connectors_can_require_durable_reliability() -> None:
    jira_cfg = load_jira_mapping_config("src/sena/examples/integrations/jira_mappings.yaml")
    with pytest.raises(JiraIntegrationError, match="durable reliability storage is required"):
        JiraConnector(
            config=jira_cfg,
            verifier=AllowAllJiraWebhookVerifier(),
            require_durable_reliability=True,
        )

    servicenow_cfg = load_servicenow_mapping_config(
        "src/sena/examples/integrations/servicenow_mappings.yaml"
    )
    with pytest.raises(
        ServiceNowIntegrationError,
        match="durable reliability storage is required",
    ):
        ServiceNowConnector(
            config=servicenow_cfg,
            require_durable_reliability=True,
        )
