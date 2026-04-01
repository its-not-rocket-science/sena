from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sena.core.models import ActionProposal
from sena.integrations.base import Connector, DecisionPayload, IntegrationError

try:
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    yaml = None


class WebhookMappingError(IntegrationError):
    """Raised when webhook payloads cannot be mapped deterministically."""


@dataclass(frozen=True)
class WebhookRoute:
    action_type: str
    payload_path: str | None = None
    request_id_path: str | None = None
    actor_id_path: str | None = None
    actor_role_path: str | None = None
    attributes: dict[str, str] | None = None
    static_attributes: dict[str, Any] | None = None


@dataclass(frozen=True)
class WebhookMappingConfig:
    providers: dict[str, dict[str, WebhookRoute]]



def _resolve_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        raise WebhookMappingError(f"Missing payload path '{path}'")
    return current



def load_webhook_mapping_config(path: str | Path) -> WebhookMappingConfig:
    config_path = Path(path)
    text = config_path.read_text(encoding="utf-8")
    if yaml is not None:
        raw = yaml.safe_load(text)
    else:
        raw = json.loads(text)
    providers_raw = raw.get("providers")
    if not isinstance(providers_raw, dict) or not providers_raw:
        raise WebhookMappingError("Webhook mapping config must contain non-empty 'providers'")

    providers: dict[str, dict[str, WebhookRoute]] = {}
    for provider, events in providers_raw.items():
        if not isinstance(events, dict) or not events:
            raise WebhookMappingError(f"Provider '{provider}' must define at least one event mapping")
        routes: dict[str, WebhookRoute] = {}
        for event_name, route in events.items():
            if not isinstance(route, dict):
                raise WebhookMappingError(
                    f"Mapping for provider '{provider}' event '{event_name}' must be an object"
                )
            try:
                routes[event_name] = WebhookRoute(
                    action_type=route["action_type"],
                    payload_path=route.get("payload_path"),
                    request_id_path=route.get("request_id_path"),
                    actor_id_path=route.get("actor_id_path"),
                    actor_role_path=route.get("actor_role_path"),
                    attributes=route.get("attributes"),
                    static_attributes=route.get("static_attributes"),
                )
            except KeyError as exc:
                raise WebhookMappingError(
                    f"Missing required mapping key for provider '{provider}' event '{event_name}': {exc}"
                ) from exc
        providers[provider] = routes
    return WebhookMappingConfig(providers=providers)


class WebhookPayloadMapper(Connector):
    name = "webhook"
    def __init__(self, config: WebhookMappingConfig):
        self._config = config

    def handle_event(self, event: dict[str, Any]) -> dict[str, Any]:
        provider = str(event.get("provider") or "").strip()
        event_type = str(event.get("event_type") or "").strip()
        payload = event.get("payload")
        default_request_id = str(event.get("default_request_id") or "").strip()
        if not provider:
            raise WebhookMappingError("Webhook event provider must be non-empty")
        if not event_type:
            raise WebhookMappingError("Webhook event_type must be non-empty")
        if not isinstance(payload, dict):
            raise WebhookMappingError("Webhook payload must be an object")
        if not default_request_id:
            raise WebhookMappingError("Webhook default_request_id must be non-empty")

        proposal = self.map_payload(
            provider=provider,
            event_type=event_type,
            payload=payload,
            default_request_id=default_request_id,
        )
        return {
            "action_type": proposal.action_type,
            "request_id": proposal.request_id,
            "actor_id": proposal.actor_id,
            "actor_role": proposal.actor_role,
            "attributes": proposal.attributes,
        }

    def send_decision(self, payload: DecisionPayload) -> dict[str, Any]:
        raise WebhookMappingError("Webhook connector does not support outbound decision delivery")

    def map_payload(
        self,
        *,
        provider: str,
        event_type: str,
        payload: dict[str, Any],
        default_request_id: str,
    ) -> ActionProposal:
        provider_map = self._config.providers.get(provider)
        if provider_map is None:
            raise WebhookMappingError(f"Unknown webhook provider '{provider}'")

        route = provider_map.get(event_type)
        if route is None:
            raise WebhookMappingError(
                f"No mapping rule configured for provider '{provider}' event '{event_type}'"
            )

        source = _resolve_path(payload, route.payload_path) if route.payload_path else payload
        if not isinstance(source, dict):
            raise WebhookMappingError(
                f"payload_path for provider '{provider}' event '{event_type}' must resolve to object"
            )

        request_id = default_request_id
        if route.request_id_path:
            resolved_request_id = _resolve_path(payload, route.request_id_path)
            request_id = str(resolved_request_id)

        actor_id = None
        if route.actor_id_path:
            actor_id = str(_resolve_path(payload, route.actor_id_path))
        actor_role = None
        if route.actor_role_path:
            actor_role = str(_resolve_path(payload, route.actor_role_path))

        attributes: dict[str, Any] = {}
        for out_key, in_path in (route.attributes or {}).items():
            attributes[out_key] = _resolve_path(source, in_path)
        attributes.update(route.static_attributes or {})

        return ActionProposal(
            action_type=route.action_type,
            request_id=request_id,
            actor_id=actor_id,
            actor_role=actor_role,
            attributes=attributes,
        )
