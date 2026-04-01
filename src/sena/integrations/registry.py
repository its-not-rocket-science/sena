from __future__ import annotations

from sena.integrations.base import ConnectorRegistry
from sena.integrations.slack import SlackClient
from sena.integrations.webhook import WebhookPayloadMapper


def build_connector_registry(
    *,
    webhook: WebhookPayloadMapper | None = None,
    slack: SlackClient | None = None,
) -> ConnectorRegistry:
    registry = ConnectorRegistry()
    if webhook is not None:
        registry.register(webhook)
    if slack is not None:
        registry.register(slack)
    return registry
