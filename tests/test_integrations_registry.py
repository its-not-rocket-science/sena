import pytest

from sena.integrations.base import ConnectorRegistry, DecisionPayload, IntegrationError
from sena.integrations.registry import build_connector_registry
from sena.integrations.slack import SlackClient
from sena.integrations.webhook import WebhookMappingConfig, WebhookPayloadMapper, WebhookRoute


def test_registry_registers_connectors() -> None:
    webhook = WebhookPayloadMapper(
        WebhookMappingConfig(
            providers={
                "partner": {
                    "created": WebhookRoute(action_type="review")
                }
            }
        )
    )
    slack = SlackClient(bot_token="xoxb-test", default_channel="#risk")

    registry = build_connector_registry(webhook=webhook, slack=slack)

    assert registry.list_names() == ["slack", "webhook"]
    assert registry.get("slack") is slack
    assert registry.get("webhook") is webhook


def test_registry_rejects_duplicate_names() -> None:
    registry = ConnectorRegistry()
    slack = SlackClient(bot_token="xoxb-test", default_channel="#risk")

    registry.register(slack)

    with pytest.raises(IntegrationError, match="already registered"):
        registry.register(slack)


def test_webhook_send_decision_not_supported() -> None:
    webhook = WebhookPayloadMapper(
        WebhookMappingConfig(
            providers={"partner": {"created": WebhookRoute(action_type="review")}}
        )
    )

    with pytest.raises(IntegrationError, match="does not support"):
        webhook.send_decision(
            DecisionPayload(
                decision_id="dec_1",
                request_id="req_1",
                action_type="review",
                matched_rule_ids=[],
                summary="noop",
            )
        )
