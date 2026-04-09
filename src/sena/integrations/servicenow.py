from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from sena.integrations.approval import (
    ApprovalConnectorBase,
    ApprovalConnectorConfig,
    ApprovalEventRoute,
    DeliveryRetryError,
    InMemoryDeadLetterQueue,
    InMemoryDeliveryIdempotencyStore,
    InMemoryDeliveryExecutionStore,
    MinimalApprovalEventContract,
    NormalizedApprovalEvent,
    ReliableDeliveryExecutor,
    build_normalized_approval_event,
    load_mapping_document,
    parse_approval_routes,
    resolve_path,
)
from sena.integrations.base import DecisionPayload, IntegrationError
from sena.policy.integration_persistence import SQLiteIntegrationReliabilityStore


class ServiceNowIntegrationError(IntegrationError):
    """Raised for deterministic ServiceNow integration failures."""


ServiceNowEventRoute = ApprovalEventRoute


@dataclass(frozen=True)
class ServiceNowOutboundConfig:
    mode: str = "callback"
    max_attempts: int = 1


@dataclass(frozen=True)
class ServiceNowMappingConfig:
    routes: dict[str, ServiceNowEventRoute]
    outbound: ServiceNowOutboundConfig = ServiceNowOutboundConfig()


class ServiceNowWebhookVerifier(Protocol):
    def verify(self, *, headers: dict[str, str], raw_body: bytes) -> None: ...


class AllowAllServiceNowWebhookVerifier:
    def verify(self, *, headers: dict[str, str], raw_body: bytes) -> None:
        return None


class RotatingSharedSecretServiceNowWebhookVerifier:
    def __init__(
        self, secrets: tuple[str, ...], signature_header: str = "x-sena-signature"
    ) -> None:
        self._secrets = tuple(secret.encode("utf-8") for secret in secrets if secret)
        self._signature_header = signature_header.lower()

    def verify(self, *, headers: dict[str, str], raw_body: bytes) -> None:
        provided = headers.get(self._signature_header, "")
        if not provided:
            raise ServiceNowIntegrationError("missing webhook signature")
        for secret in self._secrets:
            expected = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
            if hmac.compare_digest(provided, expected):
                return
        raise ServiceNowIntegrationError("invalid webhook signature")


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
    raw = load_mapping_document(path)
    routes = parse_approval_routes(
        raw,
        error_cls=ServiceNowIntegrationError,
        config_name="ServiceNow",
    )
    outbound_raw = raw.get("outbound", {}) or {}
    mode = str(outbound_raw.get("mode", "callback"))
    max_attempts = int(outbound_raw.get("max_attempts", 1))
    if mode not in {"callback", "none"}:
        raise ServiceNowIntegrationError(
            "ServiceNow outbound.mode must be one of: callback,none"
        )
    return ServiceNowMappingConfig(
        routes=routes,
        outbound=ServiceNowOutboundConfig(mode=mode, max_attempts=max_attempts),
    )


class ServiceNowConnector(ApprovalConnectorBase):
    name = "servicenow"
    source_system = "servicenow"
    error_cls = ServiceNowIntegrationError
    invalid_envelope_message = "invalid servicenow event envelope"

    def __init__(
        self,
        *,
        config: ServiceNowMappingConfig,
        idempotency_store: ServiceNowIdempotencyStore | None = None,
        reliability_store: SQLiteIntegrationReliabilityStore | None = None,
        reliability_db_path: str | None = None,
        delivery_client: ServiceNowDeliveryClient | None = None,
        verifier: ServiceNowWebhookVerifier | None = None,
    ) -> None:
        durable_store = reliability_store
        if durable_store is None and reliability_db_path:
            durable_store = SQLiteIntegrationReliabilityStore(str(Path(reliability_db_path)))
        super().__init__(
            config=ApprovalConnectorConfig(routes=config.routes),
            verifier=verifier or AllowAllServiceNowWebhookVerifier(),
            idempotency_store=idempotency_store
            or durable_store
            or InMemoryServiceNowIdempotencyStore(),
        )
        self._config = config
        self._delivery_client = delivery_client or NullServiceNowDeliveryClient()
        self._delivery_executor = ReliableDeliveryExecutor(
            max_attempts=config.outbound.max_attempts,
            completion_store=durable_store or InMemoryDeliveryExecutionStore(),
            dlq=durable_store or InMemoryDeadLetterQueue(),
        )

    def dead_letter_items(self) -> list[dict[str, Any]]:
        return [item.__dict__.copy() for item in self._delivery_executor.dlq.items()]

    def extract_event_type(self, payload: dict[str, Any]) -> str:
        event_type = str(payload.get("event_type") or payload.get("type") or "").strip()
        if not event_type:
            raise ServiceNowIntegrationError("missing event_type")
        return event_type

    def compute_delivery_id(
        self,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        event_type: str,
        route: ServiceNowEventRoute,
    ) -> str:
        del route
        source_record_id = str(
            payload.get("sys_id")
            or payload.get("change_request", {}).get("sys_id")
            or payload.get("change_request", {}).get("number")
            or ""
        ).strip()
        if not source_record_id:
            source_record_id = str(
                resolve_path(
                    payload,
                    "change_request.sys_id",
                    error_cls=ServiceNowIntegrationError,
                )
            )
        return (
            headers.get("x-servicenow-delivery-id")
            or headers.get("x-request-id")
            or f"{event_type}:{source_record_id}:{payload.get('updated_at') or payload.get('sys_updated_on') or 'na'}"
        )

    def build_normalized_event(
        self,
        *,
        payload: dict[str, Any],
        event_type: str,
        route: ServiceNowEventRoute,
        delivery_id: str,
    ) -> NormalizedServiceNowEvent:
        source_record_id = str(
            payload.get("sys_id")
            or payload.get("change_request", {}).get("sys_id")
            or payload.get("change_request", {}).get("number")
            or ""
        ).strip()
        if not source_record_id:
            source_record_id = str(
                resolve_path(
                    payload,
                    "change_request.sys_id",
                    error_cls=ServiceNowIntegrationError,
                )
            )
        default_request_id = str(
            payload.get("number")
            or payload.get("change_request", {}).get("number")
            or source_record_id
        )
        normalized = build_normalized_approval_event(
            payload=payload,
            route=route,
            source_event_type=event_type,
            idempotency_key=delivery_id,
            source_system="servicenow",
            default_request_id=default_request_id,
            default_source_record_id=source_record_id,
            error_cls=ServiceNowIntegrationError,
            default_source_object_type=str(
                payload.get("table")
                or payload.get("change_request", {}).get("table")
                or "change_request"
            ),
            default_workflow_stage="requested",
            default_requested_action=route.action_type,
            default_correlation_key=default_request_id,
            source_metadata={
                "servicenow_table": payload.get("table")
                or payload.get("change_request", {}).get("table")
                or "change_request",
                "servicenow_change_number": default_request_id,
            },
        )
        MinimalApprovalEventContract(
            source_system=normalized.source_system,
            source_event_type=normalized.source_event_type,
            request_id=normalized.request_id,
            requested_action=normalized.requested_action,
            actor_id=normalized.actor.actor_id,
            correlation_key=normalized.correlation_key,
            idempotency_key=normalized.idempotency_key,
        )
        return normalized

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
            delivery = self._delivery_executor.deliver(
                operation_key=f"{payload.decision_id}:callback:{payload.request_id or 'na'}",
                target="callback",
                payload=callback_payload,
                delivery_fn=lambda: self._delivery_client.publish_callback(
                    callback_payload
                ),
            )
        except DeliveryRetryError as exc:
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
