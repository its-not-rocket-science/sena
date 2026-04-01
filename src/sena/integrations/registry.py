from __future__ import annotations

from sena.integrations.base import ConnectorRegistry
from sena.integrations.jira import JiraConnector
from sena.integrations.servicenow import ServiceNowConnector
from sena.integrations.slack import SlackClient
from sena.integrations.webhook import WebhookPayloadMapper


def build_connector_registry(
    *,
    webhook: WebhookPayloadMapper | None = None,
    slack: SlackClient | None = None,
    jira: JiraConnector | None = None,
    servicenow: ServiceNowConnector | None = None,
) -> ConnectorRegistry:
    registry = ConnectorRegistry()
    if webhook is not None:
        registry.register(webhook)
    if slack is not None:
        registry.register(slack)
    if jira is not None:
        registry.register(jira)
    if servicenow is not None:
        registry.register(servicenow)
    return registry
