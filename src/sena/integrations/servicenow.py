from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from sena.api.logging import get_logger
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
from sena.integrations.persistence import SQLiteIntegrationReliabilityStore
from sena.integrations.reliability import resolve_durable_reliability_store

logger = get_logger(__name__)

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
        provided = _extract_servicenow_signature(
            headers=headers, signature_header=self._signature_header
        )
        if not provided:
            raise ServiceNowIntegrationError(
                "missing webhook signature (expected header: x-sena-signature or x-servicenow-signature)"
            )
        for secret in self._secrets:
            expected = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
            if hmac.compare_digest(provided, expected):
                return
        raise ServiceNowIntegrationError("invalid webhook signature")


def _extract_servicenow_signature(
    *, headers: dict[str, str], signature_header: str
) -> str:
    direct = str(headers.get(signature_header, "")).strip()
    if direct:
        return direct
    prefixed = str(headers.get("x-servicenow-signature", "")).strip()
    if prefixed.lower().startswith("sha256="):
        return prefixed.split("=", 1)[1].strip()
    return prefixed


class ServiceNowIdempotencyStore(Protocol):
    def mark_if_new(
        self, delivery_id: str, *, payload_fingerprint: str | None = None
    ) -> Literal["new", "duplicate", "conflict"]: ...


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
        require_durable_reliability: bool = False,
        delivery_client: ServiceNowDeliveryClient | None = None,
        verifier: ServiceNowWebhookVerifier | None = None,
        reliability_observer: Any | None = None,
    ) -> None:
        durable_store = resolve_durable_reliability_store(
            reliability_store=reliability_store,
            reliability_db_path=reliability_db_path,
            require_durable_reliability=require_durable_reliability,
            error_cls=ServiceNowIntegrationError,
        )
        super().__init__(
            config=ApprovalConnectorConfig(routes=config.routes),
            verifier=verifier or AllowAllServiceNowWebhookVerifier(),
            idempotency_store=idempotency_store
            or durable_store
            or InMemoryServiceNowIdempotencyStore(),
            reliability_observer=reliability_observer,
        )
        self._config = config
        self._reliability_store = durable_store
        self._delivery_client = delivery_client or NullServiceNowDeliveryClient()
        self._delivery_executor = ReliableDeliveryExecutor(
            max_attempts=config.outbound.max_attempts,
            completion_store=durable_store or InMemoryDeliveryExecutionStore(),
            dlq=durable_store or InMemoryDeadLetterQueue(),
            reliability_observer=reliability_observer,
        )
        self._reliability_observer = reliability_observer

    def dead_letter_items(self) -> list[dict[str, Any]]:
        return [item.__dict__.copy() for item in self._delivery_executor.dlq.items()]

    def outbound_completion_records(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if self._reliability_store is None:
            return []
        return [record.__dict__.copy() for record in self._reliability_store.list_completion_records(limit=limit)]

    def outbound_dead_letter_records(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if self._reliability_store is None:
            return []
        return [record.__dict__.copy() for record in self._reliability_store.list_dead_letter_records(limit=limit)]

    def outbound_duplicate_suppression_summary(self) -> dict[str, Any]:
        if self._reliability_store is None:
            return {"inbound": {}, "outbound": {}}
        return self._reliability_store.duplicate_suppression_summary()

    def outbound_reliability_summary(self) -> dict[str, Any]:
        if self._reliability_store is None:
            return {}
        return self._reliability_store.reliability_summary()

    def _normalized_admin_note(self, note: str) -> str:
        normalized = str(note).strip()
        if not normalized:
            raise ServiceNowIntegrationError("manual redrive note must not be empty")
        if len(normalized) > 1024:
            raise ServiceNowIntegrationError("manual redrive note exceeds 1024 characters")
        if any(ord(ch) < 32 for ch in normalized):
            raise ServiceNowIntegrationError(
                "manual redrive note contains control characters"
            )
        return normalized

    def replay_dead_letter(self, dead_letter_id: int) -> dict[str, Any]:
        if self._reliability_store is None:
            raise ServiceNowIntegrationError("durable reliability storage is not configured")
        record = self._reliability_store.get_dead_letter_record(dead_letter_id)
        if record is None:
            raise ServiceNowIntegrationError(f"dead-letter record not found: {dead_letter_id}")
        if record.target != "callback":
            raise ServiceNowIntegrationError(f"unsupported dead-letter target: {record.target}")
        try:
            result = self._delivery_client.publish_callback(record.payload)
        except Exception:
            self._reliability_store.record_admin_event(
                event_type="replay",
                target=record.target,
                status="failure",
            )
            if self._reliability_observer is not None:
                self._reliability_observer.record_outbound_replay(
                    target=record.target, status="failure"
                )
            logger.warning(
                "connector_outbound_dead_letter_replay_failed",
                connector=self.source_system,
                target=record.target,
                dead_letter_id=dead_letter_id,
            )
            raise
        self._reliability_store.mark_completed(
            record.operation_key,
            target=record.target,
            payload=record.payload,
            result=result if isinstance(result, dict) else {"value": result},
            attempts=record.attempts,
            max_attempts=record.max_attempts or self._config.outbound.max_attempts,
        )
        self._reliability_store.delete_dead_letter_record(dead_letter_id)
        self._reliability_store.record_admin_event(
            event_type="replay", target=record.target, status="success"
        )
        if self._reliability_observer is not None:
            self._reliability_observer.record_outbound_replay(
                target=record.target, status="success"
            )
            self._reliability_observer.record_outbound_completion(target=record.target)
            self._reliability_observer.record_outbound_dead_letter_removed()
        logger.info(
            "connector_outbound_dead_letter_replayed",
            connector=self.source_system,
            target=record.target,
            dead_letter_id=dead_letter_id,
        )
        return {"dead_letter_id": dead_letter_id, "status": "replayed", "result": result}

    def manual_redrive_dead_letter(self, dead_letter_id: int, *, note: str) -> dict[str, Any]:
        if self._reliability_store is None:
            raise ServiceNowIntegrationError("durable reliability storage is not configured")
        normalized_note = self._normalized_admin_note(note)
        record = self._reliability_store.get_dead_letter_record(dead_letter_id)
        if record is None:
            raise ServiceNowIntegrationError(f"dead-letter record not found: {dead_letter_id}")
        self._reliability_store.mark_completed(
            record.operation_key,
            target=record.target,
            payload=record.payload,
            result={"status": "manually_redriven", "note": normalized_note},
            attempts=record.attempts,
            max_attempts=record.max_attempts or self._config.outbound.max_attempts,
        )
        self._reliability_store.delete_dead_letter_record(dead_letter_id)
        self._reliability_store.record_admin_event(
            event_type="manual_redrive", target=record.target, status="success"
        )
        if self._reliability_observer is not None:
            self._reliability_observer.record_outbound_manual_redrive(
                target=record.target
            )
            self._reliability_observer.record_outbound_completion(target=record.target)
            self._reliability_observer.record_outbound_dead_letter_removed()
        logger.info(
            "connector_outbound_dead_letter_manual_redrive",
            connector=self.source_system,
            target=record.target,
            dead_letter_id=dead_letter_id,
        )
        return {"dead_letter_id": dead_letter_id, "status": "manually_redriven"}

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
