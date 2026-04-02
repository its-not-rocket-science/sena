from __future__ import annotations

import json
from pathlib import Path

import pytest

from sena.engine.evaluator import PolicyEvaluator
from sena.integrations.jira import AllowAllJiraWebhookVerifier, JiraConnector, JiraIntegrationError, load_jira_mapping_config
from sena.integrations.base import DecisionPayload
from sena.integrations.servicenow import ServiceNowConnector, ServiceNowIntegrationError, load_servicenow_mapping_config
from sena.policy.parser import load_policy_bundle


FIXTURE_ROOT = Path("tests/fixtures/integrations")
REFERENCE_FIXTURES = Path("examples/design_partner_reference/fixtures")
REFERENCE_ACTIVE_BUNDLE = Path("examples/design_partner_reference/policy_bundles/active")


def _load_fixture(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _evaluate(proposal) -> str:
    rules, meta = load_policy_bundle(REFERENCE_ACTIVE_BUNDLE)
    evaluator = PolicyEvaluator(rules, policy_bundle=meta)
    trace = evaluator.evaluate(proposal, facts={})
    return trace.outcome.value


def test_workflow_a_jira_approval_gating_happy_path_allows_low_risk_change() -> None:
    cfg = load_jira_mapping_config("examples/design_partner_reference/integration/jira_mapping.yaml")
    connector = JiraConnector(config=cfg, verifier=AllowAllJiraWebhookVerifier())
    payload = _load_fixture(FIXTURE_ROOT / "jira" / "low_risk_change_with_cab.json")

    event = connector.handle_event(
        {
            "headers": {"x-atlassian-webhook-identifier": "flagship-jira-allow"},
            "payload": payload,
            "raw_body": json.dumps(payload).encode("utf-8"),
        }
    )

    assert _evaluate(event["action_proposal"]) == "APPROVED"


def test_workflow_a_jira_approval_gating_failure_mode_blocks_high_risk_without_cab() -> None:
    cfg = load_jira_mapping_config("examples/design_partner_reference/integration/jira_mapping.yaml")
    connector = JiraConnector(config=cfg, verifier=AllowAllJiraWebhookVerifier())
    payload = _load_fixture(FIXTURE_ROOT / "jira" / "high_risk_change_missing_cab.json")

    event = connector.handle_event(
        {
            "headers": {"x-atlassian-webhook-identifier": "flagship-jira-block"},
            "payload": payload,
            "raw_body": json.dumps(payload).encode("utf-8"),
        }
    )

    assert _evaluate(event["action_proposal"]) == "BLOCKED"


@pytest.mark.parametrize(
    "fixture_name,expected_outcome",
    [
        ("servicenow_event_low_risk_with_cab", "APPROVED"),
        ("servicenow_event_emergency_privileged_no_chain", "BLOCKED"),
    ],
)
def test_workflow_b_servicenow_change_approval_with_escalation_and_callback_loop(
    fixture_name: str,
    expected_outcome: str,
) -> None:
    cfg = load_servicenow_mapping_config("examples/design_partner_reference/integration/servicenow_mapping.yaml")
    connector = ServiceNowConnector(config=cfg)
    envelope = _load_fixture(REFERENCE_FIXTURES / f"{fixture_name}.json")

    event = connector.handle_event(envelope)
    decision = _evaluate(event["action_proposal"])
    callback = connector.send_decision(
        DecisionPayload(
            decision_id="dec-flagship",
            request_id=event["action_proposal"].request_id,
            action_type=event["action_proposal"].action_type,
            matched_rule_ids=["RULE-TEST"],
            summary=decision,
        )
    )

    assert decision == expected_outcome
    assert callback["status"] == "delivered"
    assert callback["payload"]["deterministic"] is True


def test_workflow_b_servicenow_failure_mode_missing_actor_is_deterministic() -> None:
    cfg = load_servicenow_mapping_config("src/sena/examples/integrations/servicenow_mappings.yaml")
    connector = ServiceNowConnector(config=cfg)
    payload = _load_fixture(FIXTURE_ROOT / "servicenow" / "emergency_change.json")
    del payload["requested_by"]["user_id"]

    with pytest.raises(ServiceNowIntegrationError, match="missing required fields"):
        connector.handle_event(
            {
                "headers": {"x-servicenow-delivery-id": "flagship-sn-missing-actor"},
                "payload": payload,
                "raw_body": json.dumps(payload).encode("utf-8"),
            }
        )


def test_workflow_a_jira_failure_mode_missing_actor_is_deterministic() -> None:
    cfg = load_jira_mapping_config("examples/design_partner_reference/integration/jira_mapping.yaml")
    connector = JiraConnector(config=cfg, verifier=AllowAllJiraWebhookVerifier())
    payload = _load_fixture(FIXTURE_ROOT / "jira" / "low_risk_change_with_cab.json")
    payload["user"]["accountId"] = ""

    with pytest.raises(JiraIntegrationError, match="missing actor identity"):
        connector.handle_event(
            {
                "headers": {"x-atlassian-webhook-identifier": "flagship-jira-missing-actor"},
                "payload": payload,
                "raw_body": json.dumps(payload).encode("utf-8"),
            }
        )
