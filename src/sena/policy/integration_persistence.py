"""Backward-compatible import path for connector reliability persistence.

Use ``sena.integrations.persistence`` for new imports.
"""

from sena.integrations.persistence import (  # noqa: F401
    DeliveryCompletionRecord,
    PilotSQLiteIntegrationReliabilityStore,
    SQLiteIntegrationReliabilityStore,
)

__all__ = [
    "DeliveryCompletionRecord",
    "PilotSQLiteIntegrationReliabilityStore",
    "SQLiteIntegrationReliabilityStore",
]
