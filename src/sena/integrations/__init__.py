"""Integrations for external webhook and event ingestion."""

from sena.integrations.base import (
    Connector,
    ConnectorRegistry,
    DecisionPayload,
    IntegrationError,
)
from sena.integrations.registry import build_connector_registry
from sena.integrations.jira import (
    AllowAllJiraWebhookVerifier,
    InMemoryJiraIdempotencyStore,
    JiraConnector,
    JiraIntegrationError,
    JiraMappingConfig,
    JiraOutboundConfig,
    JiraEventRoute,
    SharedSecretJiraWebhookVerifier,
    load_jira_mapping_config,
)
from sena.integrations.servicenow import (
    InMemoryServiceNowIdempotencyStore,
    ServiceNowConnector,
    ServiceNowEventRoute,
    ServiceNowIntegrationError,
    ServiceNowMappingConfig,
    ServiceNowOutboundConfig,
    load_servicenow_mapping_config,
)
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
    "JiraConnector",
    "JiraIntegrationError",
    "JiraMappingConfig",
    "JiraOutboundConfig",
    "JiraEventRoute",
    "load_jira_mapping_config",
    "AllowAllJiraWebhookVerifier",
    "SharedSecretJiraWebhookVerifier",
    "InMemoryJiraIdempotencyStore",
    "WebhookMappingConfig",
    "WebhookMappingError",
    "WebhookPayloadMapper",
    "load_webhook_mapping_config",
    "ServiceNowConnector",
    "ServiceNowIntegrationError",
    "ServiceNowMappingConfig",
    "ServiceNowOutboundConfig",
    "ServiceNowEventRoute",
    "load_servicenow_mapping_config",
    "InMemoryServiceNowIdempotencyStore",
    "SlackClient",
    "SlackEscalationMessage",
    "SlackIntegrationError",
    "parse_interaction_decision",
]
