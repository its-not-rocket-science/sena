import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from sena.api.app import create_app
from sena.api.config import ApiSettings
from sena.integrations.slack import SlackClient, parse_interaction_decision


def _settings(**kwargs):
    defaults = {
        "policy_dir": "src/sena/examples/policies",
        "bundle_name": "enterprise-demo",
        "bundle_version": "2026.03",
        "enable_api_key_auth": False,
        "api_key": None,
        "audit_sink_jsonl": None,
    }
    defaults.update(kwargs)
    return ApiSettings(**defaults)


def test_slack_client_builds_approve_reject_buttons() -> None:
    client = SlackClient(bot_token="xoxb-test", default_channel="#risk-reviews")

    message = client.build_escalation_message(
        decision_id="dec_123",
        request_id="req_9",
        action_type="export_customer_data",
        matched_rule_ids=["RULE-7"],
        summary="Escalation triggered",
    )

    assert message.channel == "#risk-reviews"
    action_ids = [item["action_id"] for item in message.blocks[1]["elements"]]
    assert action_ids == ["sena_escalation_approve", "sena_escalation_reject"]


def test_parse_interaction_decision_extracts_approve() -> None:
    payload = {
        "actions": [{"action_id": "sena_escalation_approve", "value": "dec_123"}],
        "user": {"id": "U123"},
    }

    parsed = parse_interaction_decision(payload)

    assert parsed == {"decision": "APPROVE", "decision_id": "dec_123", "reviewer": "U123"}


def test_evaluate_sends_slack_on_escalation(monkeypatch) -> None:
    sent = {}

    def fake_post(self, **kwargs):
        sent.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(SlackClient, "post_escalation", fake_post)

    app = create_app(
        _settings(slack_bot_token="xoxb-test", slack_channel="#risk-reviews")
    )
    client = TestClient(app)

    response = client.post(
        "/v1/evaluate",
        json={
            "action_type": "export_customer_data",
            "attributes": {
                "requested_fields": ["customer_id", "date_of_birth"],
                "legal_basis": "contract",
                "dpo_approved": False,
            },
            "facts": {},
        },
    )

    assert response.status_code == 200
    assert response.json()["outcome"] == "ESCALATE_FOR_HUMAN_REVIEW"
    assert sent["action_type"] == "export_customer_data"
    assert sent["decision_id"].startswith("dec_")


def test_slack_interactions_endpoint() -> None:
    app = create_app(_settings())
    client = TestClient(app)

    response = client.post(
        "/v1/integrations/slack/interactions",
        data={
            "payload": json.dumps(
                {
                    "actions": [
                        {
                            "action_id": "sena_escalation_reject",
                            "value": "dec_555",
                        }
                    ],
                    "user": {"id": "U777"},
                }
            )
        },
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "REJECT"
    assert response.json()["decision_id"] == "dec_555"
