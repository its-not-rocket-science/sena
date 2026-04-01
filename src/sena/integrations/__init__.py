"""Integrations for external webhook and event ingestion."""

from sena.integrations.webhook import (
    WebhookMappingConfig,
    WebhookMappingError,
    WebhookPayloadMapper,
    load_webhook_mapping_config,
)
from sena.integrations.slack import (
    SlackClient,
    SlackEscalationMessage,
    SlackIntegrationError,
    parse_interaction_decision,
)

__all__ = [
    "WebhookMappingConfig",
    "WebhookMappingError",
    "WebhookPayloadMapper",
    "load_webhook_mapping_config",
    "SlackClient",
    "SlackEscalationMessage",
    "SlackIntegrationError",
    "parse_interaction_decision",
]
