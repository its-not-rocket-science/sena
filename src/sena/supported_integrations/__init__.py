"""Supported integration connectors and reliability adapters.

This package points contributors to productized integrations while preserving the
existing `sena.integrations.*` module paths.
"""

from sena.integrations.approval import ActionProposal, NormalizedApprovalEvent
from sena.integrations.jira import (
    AllowAllJiraWebhookVerifier,
    InMemoryJiraIdempotencyStore,
    JiraConnector,
    JiraEventRoute,
    JiraIntegrationError,
    JiraMappingConfig,
    JiraOutboundConfig,
    SharedSecretJiraWebhookVerifier,
    load_jira_mapping_config,
)
from sena.integrations.persistence import (
    DeliveryCompletionRecord,
    PilotSQLiteIntegrationReliabilityStore,
    SQLiteIntegrationReliabilityStore,
)
from sena.integrations.registry import build_connector_registry
from sena.integrations.servicenow import (
    InMemoryServiceNowIdempotencyStore,
    ServiceNowConnector,
    ServiceNowEventRoute,
    ServiceNowIntegrationError,
    ServiceNowMappingConfig,
    ServiceNowOutboundConfig,
    load_servicenow_mapping_config,
)

__all__ = [
    "ActionProposal",
    "NormalizedApprovalEvent",
    "AllowAllJiraWebhookVerifier",
    "InMemoryJiraIdempotencyStore",
    "JiraConnector",
    "JiraEventRoute",
    "JiraIntegrationError",
    "JiraMappingConfig",
    "JiraOutboundConfig",
    "SharedSecretJiraWebhookVerifier",
    "load_jira_mapping_config",
    "DeliveryCompletionRecord",
    "PilotSQLiteIntegrationReliabilityStore",
    "SQLiteIntegrationReliabilityStore",
    "build_connector_registry",
    "InMemoryServiceNowIdempotencyStore",
    "ServiceNowConnector",
    "ServiceNowEventRoute",
    "ServiceNowIntegrationError",
    "ServiceNowMappingConfig",
    "ServiceNowOutboundConfig",
    "load_servicenow_mapping_config",
]
