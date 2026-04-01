from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from sena.integrations.approval import (
    ApprovalEventRoute,
    InMemoryDeliveryIdempotencyStore,
    NormalizedApprovalEvent,
    build_normalized_approval_event,
    resolve_path,
    to_action_proposal,
)
from sena.integrations.base import Connector, DecisionPayload, IntegrationError


class ServiceNowIntegrationError(IntegrationError):
    """Raised for deterministic ServiceNow integration failures."""


ServiceNowEventRoute = ApprovalEventRoute


@dataclass(frozen=True)
class ServiceNowOutboundConfig:
    mode: str = "callback"


@dataclass(frozen=True)
class ServiceNowMappingConfig:
    routes: dict[str, ServiceNowEventRoute]
    outbound: ServiceNowOutboundConfig = ServiceNowOutboundConfig()


class ServiceNowIdempotencyStore(Protocol):
    def mark_if_new(self, delivery_id: str) -> bool: ...


InMemoryServiceNowIdempotencyStore = InMemoryDeliveryIdempotencyStore
NormalizedServiceNowEvent = NormalizedApprovalEvent


class ServiceNowDeliveryClient(Protocol):
    def publish_callback(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class NullServiceNowDeliveryClient:
    def publish_callback(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "skipped",
            "target": "callback",
            "request_id": payload.get("request_id"),
        }


def load_servicenow_mapping_config(path: str) -> ServiceNowMappingConfig:
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError:
        yaml = None

    text = open(path, encoding="utf-8").read()
    raw = yaml.safe_load(text) if yaml else json.loads(text)
    routes_raw = raw.get("routes")
    if not isinstance(routes_raw, dict) or not routes_raw:
        raise ServiceNowIntegrationError("ServiceNow mapping config must define non-empty routes")

    routes: dict[str, ServiceNowEventRoute] = {}
    for event_type, route in routes_raw.items():
        if not isinstance(route, dict):
            raise ServiceNowIntegrationError(f"route '{event_type}' must be an object")
        if "action_type" not in route or "actor_id_path" not in route:
            raise ServiceNowIntegrationError(f"route '{event_type}' missing required keys")
        attrs = route.get("attributes", {})
        if not isinstance(attrs, dict):
            raise ServiceNowIntegrationError(f"route '{event_type}' attributes must be an object")
        required_fields = route.get("required_fields", [])
        if not isinstance(required_fields, list):
            raise ServiceNowIntegrationError(f"route '{event_type}' required_fields must be a list")

        routes[event_type] = ServiceNowEventRoute(
            action_type=str(route["action_type"]),
            actor_id_path=str(route["actor_id_path"]),
            actor_role_path=route.get("actor_role_path"),
            request_id_path=route.get("request_id_path"),
            source_record_id_path=route.get("source_record_id_path"),
            attributes={str(k): str(v) for k, v in attrs.items()},
            required_fields=[str(item) for item in required_fields],
            static_attributes=route.get("static_attributes", {}) or {},
            policy_bundle=route.get("policy_bundle"),
        )
    outbound_raw = raw.get("outbound", {}) or {}
    mode = str(outbound_raw.get("mode", "callback"))
    if mode not in {"callback", "none"}:
        raise ServiceNowIntegrationError("ServiceNow outbound.mode must be one of: callback,none")
    return ServiceNowMappingConfig(routes=routes, outbound=ServiceNowOutboundConfig(mode=mode))


class ServiceNowConnector(Connector):
    name = "servicenow"

    def __init__(
        self,
        *,
        config: ServiceNowMappingConfig,
        idempotency_store: ServiceNowIdempotencyStore | None = None,
        delivery_client: ServiceNowDeliveryClient | None = None,
    ) -> None:
        self._config = config
        self._idempotency = idempotency_store or InMemoryServiceNowIdempotencyStore()
        self._delivery_client = delivery_client or NullServiceNowDeliveryClient()

    def handle_event(self, event: dict[str, Any]) -> dict[str, Any]:
        headers = event.get("headers") or {}
        payload = event.get("payload") or {}
        raw_body = event.get("raw_body") or b""
        if not isinstance(headers, dict) or not isinstance(payload, dict) or not isinstance(raw_body, bytes):
            raise ServiceNowIntegrationError("invalid servicenow event envelope")
        normalized = self.normalize_event(headers=headers, payload=payload)
        proposal = self.map_to_proposal(normalized)
        return {"normalized_event": normalized.model_dump(), "action_proposal": proposal}

    def normalize_event(
        self,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> NormalizedServiceNowEvent:
        lowered_headers = {str(k).lower(): str(v) for k, v in headers.items()}
        event_type = str(payload.get("event_type") or payload.get("type") or "").strip()
        if not event_type:
            raise ServiceNowIntegrationError("missing event_type")
        route = self._config.routes.get(event_type)
        if route is None:
            raise ServiceNowIntegrationError(f"unsupported servicenow event type '{event_type}'")

        source_record_id = str(
            payload.get("sys_id")
            or payload.get("change_request", {}).get("sys_id")
            or payload.get("change_request", {}).get("number")
            or ""
        ).strip()
        if not source_record_id:
            source_record_id = str(resolve_path(payload, "change_request.sys_id", error_cls=ServiceNowIntegrationError))
        delivery_id = (
            lowered_headers.get("x-servicenow-delivery-id")
            or lowered_headers.get("x-request-id")
            or f"{event_type}:{source_record_id}:{payload.get('updated_at') or payload.get('sys_updated_on') or 'na'}"
        )
        if not self._idempotency.mark_if_new(delivery_id):
            raise ServiceNowIntegrationError(f"duplicate delivery '{delivery_id}'")

        default_request_id = str(
            payload.get("number") or payload.get("change_request", {}).get("number") or source_record_id
        )
        return build_normalized_approval_event(
            payload=payload,
            route=route,
            event_type=event_type,
            delivery_id=delivery_id,
            source_system="servicenow",
            default_request_id=default_request_id,
            default_source_record_id=source_record_id,
            error_cls=ServiceNowIntegrationError,
            source_metadata={
                "servicenow_table": payload.get("table") or payload.get("change_request", {}).get("table") or "change_request",
                "servicenow_change_number": default_request_id,
            },
        )

    def map_to_proposal(self, event: NormalizedServiceNowEvent):
        route = self._config.routes[event.event_type]
        return to_action_proposal(event, route)

    def send_decision(self, payload: DecisionPayload) -> dict[str, Any]:
        callback_payload = {
            "schema_version": "1",
            "source_system": "servicenow",
            "decision_id": payload.decision_id,
            "request_id": payload.request_id,
            "action_type": payload.action_type,
            "decision": payload.summary,
            "matched_rule_ids": payload.matched_rule_ids,
            "status": "completed",
            "deterministic": True,
        }
        if self._config.outbound.mode == "none":
            return {"status": "skipped", "payload": callback_payload}
        try:
            delivery = self._delivery_client.publish_callback(callback_payload)
        except Exception as exc:  # pragma: no cover
            return {
                "status": "delivery_failed",
                "error": str(exc),
                "payload": callback_payload,
            }
        return {
            "status": "delivered",
            "payload": callback_payload,
            "delivery": delivery,
        }

    def route_for_event_type(self, event_type: str) -> ServiceNowEventRoute | None:
        return self._config.routes.get(event_type)
