from __future__ import annotations

import json
import logging

import pytest

pytest.importorskip("prometheus_client")

from sena.api.logging import JsonFormatter
from sena.monitoring.dashboard import TractionMetrics
from prometheus_client import CollectorRegistry


def test_traction_metrics_observability_snapshot_contract() -> None:
    metrics = TractionMetrics(registry=CollectorRegistry())
    metrics.observe_connector_inbound_event_received(
        connector="jira", event_type="jira:issue_updated"
    )
    metrics.observe_connector_outcome(
        connector="jira",
        policy_bundle="enterprise-demo:2026.03",
        outcome="BLOCKED",
    )
    metrics.observe_exception_overlay_applied(
        connector="jira",
        policy_bundle="enterprise-demo:2026.03",
        outcome="APPROVED",
    )
    metrics.observe_job_submitted(job_type="simulation")
    metrics.observe_job_terminal(job_type="simulation", status="succeeded")

    snapshot = metrics.observability_snapshot()
    assert snapshot["inbound_events_received"] == [
        {"connector": "jira", "event_type": "jira:issue_updated", "count": 1}
    ]
    assert snapshot["outcomes_by_connector_policy_bundle"] == [
        {
            "connector": "jira",
            "policy_bundle": "enterprise-demo:2026.03",
            "outcome": "BLOCKED",
            "count": 1,
        }
    ]
    assert snapshot["exception_overlays_applied"] == [
        {
            "connector": "jira",
            "policy_bundle": "enterprise-demo:2026.03",
            "outcome": "APPROVED",
            "count": 1,
        }
    ]


def test_json_formatter_includes_stable_structured_fields() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="sena.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="connector_inbound_event_received",
        args=(),
        exc_info=None,
    )
    record.connector = "jira"
    record.event_type = "jira:issue_updated"
    record.policy_bundle = "enterprise-demo:2026.03"
    record.error_code = "jira_authentication_failed"

    payload = json.loads(formatter.format(record))
    assert payload["message"] == "connector_inbound_event_received"
    assert payload["connector"] == "jira"
    assert payload["event_type"] == "jira:issue_updated"
    assert payload["policy_bundle"] == "enterprise-demo:2026.03"
    assert payload["error_code"] == "jira_authentication_failed"
