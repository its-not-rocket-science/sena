from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from sena.integrations.approval import DeadLetterItem, ReliableDeliveryExecutor
from sena.integrations.persistence import SQLiteIntegrationReliabilityStore


def _settings(tmp_path):
    from sena.api.config import ApiSettings

    return ApiSettings(
        policy_dir="src/sena/examples/policies",
        bundle_name="enterprise-demo",
        bundle_version="2026.03",
        processing_sqlite_path=str(tmp_path / "runtime.db"),
        jira_mapping_config_path="src/sena/examples/integrations/jira_mappings.yaml",
        jira_webhook_secret="secret",
        integration_reliability_sqlite_path=str(tmp_path / "reliability.db"),
    )


def test_outbound_observability_api_endpoints(tmp_path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from sena.api.app import create_app

    settings = _settings(tmp_path)
    store = SQLiteIntegrationReliabilityStore(str(tmp_path / "reliability.db"))
    store.mark_if_new("delivery-1")
    store.mark_if_new("delivery-1")
    store.mark_completed(
        "op-1",
        target="comment",
        payload={"issue_key": "RISK-1"},
        result={"status": "ok"},
        attempts=1,
        max_attempts=2,
    )
    store.push(
        DeadLetterItem(
            operation_key="op-2",
            target="comment",
            error="timeout",
            attempts=2,
            payload={"issue_key": "RISK-2", "message": "retry me"},
            max_attempts=2,
        )
    )

    app = create_app(settings)
    client = TestClient(app)
    completions = client.get("/v1/integrations/jira/admin/outbound/completions")
    assert completions.status_code == 200
    assert completions.json()["status"] == "ok"
    assert completions.json()["count"] == 1
    assert completions.json()["items"][0]["operation_key"] == "op-1"

    dead_letter = client.get("/v1/integrations/jira/admin/outbound/dead-letter")
    assert dead_letter.status_code == 200
    assert dead_letter.json()["status"] == "ok"
    assert dead_letter.json()["count"] == 1
    dead_letter_id = int(dead_letter.json()["items"][0]["id"])

    summary = client.get("/v1/integrations/jira/admin/outbound/duplicates/summary")
    assert summary.status_code == 200
    assert summary.json()["status"] == "ok"
    assert summary.json()["inbound"]["suppressed_total"] == 1

    redrive = client.post(
        "/v1/integrations/jira/admin/outbound/dead-letter/manual-redrive",
        params={"note": "handled in jira workflow"},
        json=[dead_letter_id],
    )
    assert redrive.status_code == 200
    assert redrive.json()["status"] == "ok"
    assert redrive.json()["count"] == 1
    assert redrive.json()["items"][0]["status"] == "manually_redriven"
    assert store.get_dead_letter_record(dead_letter_id) is None
    reliability_summary = client.get(
        "/v1/integrations/jira/admin/outbound/reliability/summary"
    )
    assert reliability_summary.status_code == 200
    assert reliability_summary.json()["status"] == "ok"
    assert reliability_summary.json()["dead_letter_volume"] == 0
    assert reliability_summary.json()["manual_redrive_total"] == 1
    assert reliability_summary.json()["completion_by_target"]["comment"] == 2


def test_cli_integrations_reliability_commands(tmp_path) -> None:
    store = SQLiteIntegrationReliabilityStore(str(tmp_path / "reliability.db"))
    store.mark_if_new("delivery-1")
    store.mark_if_new("delivery-1")
    store.mark_completed(
        "op-1",
        target="callback",
        payload={"request_id": "CR-1"},
        result={"status": "ok"},
        attempts=1,
        max_attempts=1,
    )
    store.push(
        DeadLetterItem(
            operation_key="op-2",
            target="callback",
            error="timeout",
            attempts=1,
            payload={"request_id": "CR-2"},
            max_attempts=1,
        )
    )
    dlq_id = store.list_dead_letter_records(limit=1)[0].id
    base = [
        sys.executable,
        "-m",
        "sena.cli.main",
        "integrations-reliability",
        "--sqlite-path",
        str(tmp_path / "reliability.db"),
    ]
    completions = subprocess.run(
        [*base, "completions"],
        check=True,
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": "src"},
    )
    assert json.loads(completions.stdout)["items"][0]["operation_key"] == "op-1"

    summary = subprocess.run(
        [*base, "duplicates-summary"],
        check=True,
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": "src"},
    )
    assert json.loads(summary.stdout)["inbound"]["suppressed_total"] == 1

    redrive = subprocess.run(
        [*base, "manual-redrive", "--id", str(dlq_id)],
        check=True,
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": "src"},
    )
    assert json.loads(redrive.stdout)["items"][0]["dead_letter_id"] == dlq_id


def test_outbound_duplicate_suppression_summary_tracks_executor_hits(tmp_path) -> None:
    store = SQLiteIntegrationReliabilityStore(str(tmp_path / "reliability.db"))
    executor = ReliableDeliveryExecutor(max_attempts=1, completion_store=store, dlq=store)
    first = executor.deliver(
        operation_key="op-duplicate",
        target="comment",
        payload={"issue_key": "RISK-3"},
        delivery_fn=lambda: {"status": "ok"},
    )
    second = executor.deliver(
        operation_key="op-duplicate",
        target="comment",
        payload={"issue_key": "RISK-3"},
        delivery_fn=lambda: {"status": "ok"},
    )
    assert first["status"] == "delivered"
    assert second["status"] == "duplicate_suppressed"
    assert store.duplicate_suppression_summary()["outbound"]["suppressed_total"] == 1


def test_connector_reliability_metrics_cover_duplicate_dlq_replay_and_completion(tmp_path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from sena.api.app import create_app
    from sena.integrations.jira import (
        AllowAllJiraWebhookVerifier,
        JiraConnector,
        JiraIntegrationError,
        load_jira_mapping_config,
    )

    class _Client:
        def publish_comment(self, issue_key: str, message: str) -> dict:
            return {"status": "ok", "issue_key": issue_key, "message": message}

        def publish_status(self, issue_key: str, payload: dict) -> dict:
            return {"status": "ok", "issue_key": issue_key, "payload": payload}

    settings = _settings(tmp_path)
    app = create_app(settings)
    app.state.engine_state.jira_connector = JiraConnector(
        config=load_jira_mapping_config("src/sena/examples/integrations/jira_mappings.yaml"),
        verifier=AllowAllJiraWebhookVerifier(),
        reliability_db_path=str(tmp_path / "reliability.db"),
        delivery_client=_Client(),
        reliability_observer=app.state.engine_state.metrics.connector_reliability_observer(
            connector="jira"
        ),
    )
    client = TestClient(app)

    payload = {
        "webhookEvent": "jira:issue_updated",
        "timestamp": 1711982000,
        "issue": {
            "id": "10001",
            "key": "RISK-1",
            "fields": {
                "customfield_approval_amount": 12000,
                "customfield_requester_role": "finance_analyst",
                "customfield_vendor_verified": False,
                "customfield_tenant_id": "tenant-finance",
                "customfield_workflow_id": "wf-ap-01",
                "customfield_business_unit": "finance",
                "customfield_sla_deadline_at": "2026-04-11T00:00:00Z",
                "customfield_escalation_deadline_at": "2026-04-10T18:00:00Z",
                "status": {"name": "Pending Approval"},
                "previous_status": {"name": "In Review"},
                "priority": {"name": "P2"},
            },
        },
        "user": {"accountId": "acct-1"},
        "changelog": {"items": [{"field": "status", "toString": "Pending Approval"}]},
    }
    envelope = {
        "headers": {"x-atlassian-webhook-identifier": "dup-1"},
        "payload": payload,
        "raw_body": json.dumps(payload).encode("utf-8"),
    }
    app.state.engine_state.jira_connector.handle_event(envelope)
    with pytest.raises(JiraIntegrationError, match="duplicate delivery"):
        app.state.engine_state.jira_connector.handle_event(envelope)
    store = SQLiteIntegrationReliabilityStore(str(tmp_path / "reliability.db"))
    store.push(
        DeadLetterItem(
            operation_key="op-r1",
            target="comment",
            error="timeout",
            attempts=1,
            payload={"issue_key": "RISK-1", "message": "retry"},
            max_attempts=1,
        )
    )
    dead_letter_id = store.list_dead_letter_records(limit=1)[0].id
    replay = client.post(
        "/v1/integrations/jira/admin/outbound/dead-letter/replay",
        json=[dead_letter_id],
    )
    assert replay.status_code == 200
    metrics_body = client.get("/v1/metrics/prometheus").text
    assert 'sena_connector_inbound_duplicate_suppression_total{connector="jira"} 1.0' in metrics_body
    assert 'sena_connector_outbound_replay_total{connector="jira",status="success",target="comment"} 1.0' in metrics_body
    assert 'sena_connector_outbound_completion_total{connector="jira",target="comment"} 1.0' in metrics_body
