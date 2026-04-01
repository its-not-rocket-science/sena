"""Integrations for external webhook and event ingestion."""

from sena.integrations.base import Connector, ConnectorRegistry, DecisionPayload, IntegrationError
from sena.integrations.registry import build_connector_registry
from sena.integrations.slack import (
    SlackClient,
    SlackEscalationMessage,
    SlackIntegrationError,
    parse_interaction_decision,
)
from sena.integrations.webhook import (
    WebhookMappingConfig,
    WebhookMappingError,
    WebhookPayloadMapper,
    load_webhook_mapping_config,
)

__all__ = [
    "Connector",
    "ConnectorRegistry",
    "DecisionPayload",
    "IntegrationError",
    "build_connector_registry",
    "WebhookMappingConfig",
    "WebhookMappingError",
    "WebhookPayloadMapper",
    "load_webhook_mapping_config",
    "SlackClient",
    "SlackEscalationMessage",
    "SlackIntegrationError",
    "parse_interaction_decision",
]
