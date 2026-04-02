from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sena.core.models import ActionProposal
from sena.integrations.approval import (
    ApprovalEventRoute,
    NormalizedApprovalEvent,
    build_normalized_approval_event,
    resolve_path,
    to_action_proposal,
)
from sena.integrations.base import Connector, DecisionPayload, IntegrationError

try:
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    yaml = None


class WebhookMappingError(IntegrationError):
    """Raised when webhook payloads cannot be mapped deterministically."""


WebhookRoute = ApprovalEventRoute


@dataclass(frozen=True)
class WebhookMappingConfig:
    providers: dict[str, dict[str, WebhookRoute]]


def _resolve_path(payload: dict[str, Any], path: str) -> Any:
    return resolve_path(payload, path, error_cls=WebhookMappingError)


def load_webhook_mapping_config(path: str | Path) -> WebhookMappingConfig:
    config_path = Path(path)
    text = config_path.read_text(encoding="utf-8")
    if yaml is not None:
        raw = yaml.safe_load(text)
    else:
        raw = json.loads(text)
    providers_raw = raw.get("providers")
    if not isinstance(providers_raw, dict) or not providers_raw:
        raise WebhookMappingError(
            "Webhook mapping config must contain non-empty 'providers'"
        )

    providers: dict[str, dict[str, WebhookRoute]] = {}
    for provider, events in providers_raw.items():
        if not isinstance(events, dict) or not events:
            raise WebhookMappingError(
                f"Provider '{provider}' must define at least one event mapping"
            )
        routes: dict[str, WebhookRoute] = {}
        for event_name, route in events.items():
            if not isinstance(route, dict):
                raise WebhookMappingError(
                    f"Mapping for provider '{provider}' event '{event_name}' must be an object"
                )
            try:
                attrs = route.get("attributes", {}) or {}
                if not isinstance(attrs, dict):
                    raise WebhookMappingError(
                        f"Provider '{provider}' event '{event_name}' attributes must be an object"
                    )
                routes[event_name] = WebhookRoute(
                    action_type=route["action_type"],
                    actor_id_path=route["actor_id_path"],
                    attributes={str(k): str(v) for k, v in attrs.items()},
                    required_fields=[
                        str(item) for item in route.get("required_fields", [])
                    ],
                    static_attributes=route.get("static_attributes", {}) or {},
                    payload_path=route.get("payload_path"),
                    request_id_path=route.get("request_id_path"),
                    actor_role_path=route.get("actor_role_path"),
                    source_record_id_path=route.get("source_record_id_path"),
                    source_object_type_path=route.get("source_object_type_path"),
                    workflow_stage_path=route.get("workflow_stage_path"),
                    requested_action_path=route.get("requested_action_path"),
                    correlation_key_path=route.get("correlation_key_path"),
                    idempotency_key_path=route.get("idempotency_key_path"),
                    risk_attributes={
                        str(k): str(v)
                        for k, v in (route.get("risk_attributes", {}) or {}).items()
                    },
                    evidence_references_path=route.get("evidence_references_path"),
                    static_source_object_type=route.get("static_source_object_type"),
                    static_workflow_stage=route.get("static_workflow_stage"),
                    static_requested_action=route.get("static_requested_action"),
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

        normalized = self.normalize_event(
            provider=provider,
            event_type=event_type,
            payload=payload,
            default_request_id=default_request_id,
        )
        proposal = self.map_to_proposal(provider=provider, event=normalized)
        return {
            "normalized_event": normalized.model_dump(),
            "action_proposal": proposal,
        }

    def send_decision(self, payload: DecisionPayload) -> dict[str, Any]:
        raise WebhookMappingError(
            "Webhook connector does not support outbound decision delivery"
        )

    def normalize_event(
        self,
        *,
        provider: str,
        event_type: str,
        payload: dict[str, Any],
        default_request_id: str,
    ) -> NormalizedApprovalEvent:
        provider_map = self._config.providers.get(provider)
        if provider_map is None:
            raise WebhookMappingError(f"Unknown webhook provider '{provider}'")

        route = provider_map.get(event_type)
        if route is None:
            raise WebhookMappingError(
                f"No mapping rule configured for provider '{provider}' event '{event_type}'"
            )

        source = (
            _resolve_path(payload, route.payload_path)
            if route.payload_path
            else payload
        )
        if not isinstance(source, dict):
            raise WebhookMappingError(
                f"payload_path for provider '{provider}' event '{event_type}' must resolve to object"
            )

        source_id = str(payload.get("id") or default_request_id)
        return build_normalized_approval_event(
            payload=source,
            route=route,
            source_event_type=event_type,
            idempotency_key=f"{provider}:{event_type}:{source_id}",
            source_system=provider,
            default_request_id=default_request_id,
            default_source_record_id=source_id,
            error_cls=WebhookMappingError,
            source_metadata={"provider": provider},
            default_source_object_type=f"{provider}_object",
            default_workflow_stage="intake",
            default_requested_action=route.action_type,
            default_correlation_key=default_request_id,
        )

    def map_to_proposal(
        self, *, provider: str, event: NormalizedApprovalEvent
    ) -> ActionProposal:
        route = self._config.providers[provider][event.source_event_type]
        return to_action_proposal(event, route)
