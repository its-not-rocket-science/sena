from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


class IntegrationError(RuntimeError):
    """Base integration error for deterministic connector failures."""


@dataclass(frozen=True)
class DecisionPayload:
    decision_id: str
    request_id: str | None
    action_type: str
    matched_rule_ids: list[str]
    summary: str


class Connector(ABC):
    """Pluggable integration connector interface."""

    name: str

    @abstractmethod
    def handle_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Transform inbound integration events into normalized payloads."""

    @abstractmethod
    def send_decision(self, payload: DecisionPayload) -> dict[str, Any]:
        """Deliver engine decisions to integration destinations."""


class ConnectorRegistry:
    """In-memory registry for integration connectors."""

    def __init__(self) -> None:
        self._connectors: dict[str, Connector] = {}

    def register(self, connector: Connector) -> None:
        key = connector.name.strip().lower()
        if not key:
            raise IntegrationError("Connector name must be non-empty")
        if key in self._connectors:
            raise IntegrationError(f"Connector '{key}' is already registered")
        self._connectors[key] = connector

    def get(self, name: str) -> Connector:
        key = name.strip().lower()
        connector = self._connectors.get(key)
        if connector is None:
            raise IntegrationError(f"Unknown connector '{name}'")
        return connector

    def list_names(self) -> list[str]:
        return sorted(self._connectors)
