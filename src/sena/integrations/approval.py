from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from sena.core.enums import ActionOrigin
from sena.core.models import ActionProposal, AutonomousToolMetadata
from sena.api.logging import get_logger
from sena.integrations.base import Connector, IntegrationError

logger = get_logger(__name__)


@dataclass(frozen=True)
class ApprovalEventRoute:
    action_type: str
    actor_id_path: str
    attributes: dict[str, str]
    required_fields: list[str] = field(default_factory=list)
    static_attributes: dict[str, Any] = field(default_factory=dict)
    payload_path: str | None = None
    request_id_path: str | None = None
    actor_role_path: str | None = None
    source_record_id_path: str | None = None
    policy_bundle: str | None = None
    source_object_type_path: str | None = None
    workflow_stage_path: str | None = None
    requested_action_path: str | None = None
    correlation_key_path: str | None = None
    idempotency_key_path: str | None = None
    risk_attributes: dict[str, str] = field(default_factory=dict)
    evidence_references_path: str | None = None
    static_source_object_type: str | None = None
    static_workflow_stage: str | None = None
    static_requested_action: str | None = None
    external_state_path: str | None = None
    previous_external_state_path: str | None = None
    external_to_internal_state: dict[str, str] = field(default_factory=dict)
    internal_to_external_state: dict[str, str] = field(default_factory=dict)
    allowed_state_transitions: dict[str, list[str]] = field(default_factory=dict)
    context_fields: dict[str, str] = field(default_factory=dict)
    metadata_fields: dict[str, str] = field(default_factory=dict)
    required_metadata_fields: list[str] = field(default_factory=list)
    sla_deadline_path: str | None = None
    escalation_deadline_path: str | None = None


class DeliveryIdempotencyStore(Protocol):
    def mark_if_new(
        self, delivery_id: str, *, payload_fingerprint: str | None = None
    ) -> Literal["new", "duplicate", "conflict"]: ...


class DeliveryCompletionStore(Protocol):
    def mark_completed(
        self,
        operation_key: str,
        *,
        target: str,
        payload: dict[str, Any],
        result: dict[str, Any] | None,
        attempts: int,
        max_attempts: int,
    ) -> None: ...

    def has_completed(self, operation_key: str) -> bool: ...


class DeadLetterQueue(Protocol):
    def push(self, item: "DeadLetterItem") -> None: ...

    def items(self) -> list["DeadLetterItem"]: ...


class ConnectorReliabilityObserver(Protocol):
    def record_inbound_duplicate_suppression(self) -> None: ...

    def record_outbound_duplicate_suppression(self, *, target: str) -> None: ...

    def record_outbound_dead_letter(self, *, target: str) -> None: ...

    def record_outbound_completion(self, *, target: str) -> None: ...

    def record_outbound_dead_letter_removed(self) -> None: ...

    def record_outbound_replay(self, *, target: str, status: str) -> None: ...

    def record_outbound_manual_redrive(self, *, target: str) -> None: ...


class InMemoryDeliveryIdempotencyStore:
    def __init__(self) -> None:
        self._seen: dict[str, str | None] = {}

    def mark_if_new(
        self, delivery_id: str, *, payload_fingerprint: str | None = None
    ) -> Literal["new", "duplicate", "conflict"]:
        existing = self._seen.get(delivery_id)
        if existing is None:
            self._seen[delivery_id] = payload_fingerprint
            return "new"
        if existing == payload_fingerprint:
            return "duplicate"
        return "conflict"


class NormalizedActor(BaseModel):
    actor_id: str
    actor_role: str | None = None


class NormalizedApprovalEvent(BaseModel):
    schema_version: str = "1"
    source_system: str
    source_event_type: str
    source_object_type: str
    source_object_id: str
    workflow_stage: str
    requested_action: str
    actor: NormalizedActor
    request_id: str
    event_timestamp: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    risk_attributes: dict[str, Any] = Field(default_factory=dict)
    evidence_references: list[str] = Field(default_factory=list)
    correlation_key: str
    idempotency_key: str
    external_state: str | None = None
    previous_external_state: str | None = None
    sla_deadline_at: str | None = None
    escalation_deadline_at: str | None = None
    source_metadata: dict[str, Any] = Field(default_factory=dict)

    def canonical_replay_payload(self) -> dict[str, Any]:
        """Replay-stable event payload used by deterministic comparison tests."""
        payload = self.model_dump()
        payload.pop("event_timestamp", None)
        return payload

    def operational_metadata(self) -> dict[str, Any]:
        return {"event_timestamp": self.event_timestamp}


class DeliveryRetryError(IntegrationError):
    """Raised when outbound delivery exhausts retry budget."""


@dataclass(frozen=True)
class DeadLetterItem:
    operation_key: str
    target: str
    error: str
    attempts: int
    payload: dict[str, Any]
    max_attempts: int | None = None
    first_failed_at: str | None = None
    last_failed_at: str | None = None


class InMemoryDeadLetterQueue:
    def __init__(self) -> None:
        self._items: list[DeadLetterItem] = []

    def push(self, item: DeadLetterItem) -> None:
        self._items.append(item)

    def items(self) -> list[DeadLetterItem]:
        return list(self._items)


class InMemoryDeliveryExecutionStore:
    def __init__(self) -> None:
        self._completed: set[str] = set()

    def mark_completed(
        self,
        operation_key: str,
        *,
        target: str,
        payload: dict[str, Any],
        result: dict[str, Any] | None,
        attempts: int,
        max_attempts: int,
    ) -> None:
        del target, payload, result, attempts, max_attempts
        self._completed.add(operation_key)

    def has_completed(self, operation_key: str) -> bool:
        return operation_key in self._completed


class ReliableDeliveryExecutor:
    def __init__(
        self,
        *,
        max_attempts: int,
        completion_store: DeliveryCompletionStore | None = None,
        dlq: DeadLetterQueue | None = None,
        reliability_observer: ConnectorReliabilityObserver | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self._max_attempts = max_attempts
        self._completion_store = completion_store or InMemoryDeliveryExecutionStore()
        self._dlq = dlq or InMemoryDeadLetterQueue()
        self._reliability_observer = reliability_observer

    @property
    def dlq(self) -> DeadLetterQueue:
        return self._dlq

    def deliver(
        self,
        *,
        operation_key: str,
        target: str,
        payload: dict[str, Any],
        delivery_fn: Any,
    ) -> dict[str, Any]:
        if self._completion_store.has_completed(operation_key):
            recorder = getattr(
                self._completion_store, "record_outbound_duplicate_suppression", None
            )
            if callable(recorder):
                recorder(operation_key=operation_key, target=target)
            if self._reliability_observer is not None:
                self._reliability_observer.record_outbound_duplicate_suppression(
                    target=target
                )
            return {
                "status": "duplicate_suppressed",
                "target": target,
                "operation_key": operation_key,
            }
        last_error: str | None = None
        first_failed_at: str | None = None
        last_failed_at: str | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                result = delivery_fn()
            except Exception as exc:  # pragma: no cover - exercised via connector tests
                last_error = str(exc)
                now = datetime.now(timezone.utc).isoformat()
                if first_failed_at is None:
                    first_failed_at = now
                last_failed_at = now
                if attempt == self._max_attempts:
                    self._dlq.push(
                        DeadLetterItem(
                            operation_key=operation_key,
                            target=target,
                            error=last_error,
                            attempts=attempt,
                            payload=payload,
                            max_attempts=self._max_attempts,
                            first_failed_at=first_failed_at,
                            last_failed_at=last_failed_at,
                        )
                    )
                    if self._reliability_observer is not None:
                        self._reliability_observer.record_outbound_dead_letter(
                            target=target
                        )
                    raise DeliveryRetryError(
                        f"delivery failed after {attempt} attempts: {last_error}"
                    ) from exc
                continue
            self._completion_store.mark_completed(
                operation_key,
                target=target,
                payload=payload,
                result=result if isinstance(result, dict) else {"value": result},
                attempts=attempt,
                max_attempts=self._max_attempts,
            )
            if self._reliability_observer is not None:
                self._reliability_observer.record_outbound_completion(target=target)
            return {"status": "delivered", "target": target, "result": result}
        raise DeliveryRetryError(
            f"delivery failed after {self._max_attempts} attempts: {last_error or 'unknown'}"
        )


class MinimalApprovalEventContract(BaseModel):
    """Stable minimum event envelope required by the policy engine."""

    schema_version: str = "1"
    source_system: str
    source_event_type: str
    request_id: str
    requested_action: str
    actor_id: str
    correlation_key: str
    idempotency_key: str


class ApprovalWebhookVerifier(Protocol):
    def verify(self, *, headers: dict[str, str], raw_body: bytes) -> None: ...


@dataclass(frozen=True)
class ApprovalConnectorConfig:
    routes: dict[str, ApprovalEventRoute]


def load_mapping_document(path: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError:
        yaml = None

    text = Path(path).read_text(encoding="utf-8")
    raw = yaml.safe_load(text) if yaml else json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError("mapping config must be an object")
    return raw


def parse_approval_routes(
    raw: dict[str, Any], *, error_cls: type[IntegrationError], config_name: str
) -> dict[str, ApprovalEventRoute]:
    routes_raw = raw.get("routes")
    if not isinstance(routes_raw, dict) or not routes_raw:
        raise error_cls(f"{config_name} mapping config must define non-empty routes")
    routes: dict[str, ApprovalEventRoute] = {}
    for event_type, route in routes_raw.items():
        if not isinstance(route, dict):
            raise error_cls(f"route '{event_type}' must be an object")
        if "action_type" not in route or "actor_id_path" not in route:
            raise error_cls(f"route '{event_type}' missing required keys")
        attrs = route.get("attributes", {})
        if not isinstance(attrs, dict):
            raise error_cls(f"route '{event_type}' attributes must be an object")
        required_fields = route.get("required_fields", [])
        if not isinstance(required_fields, list):
            raise error_cls(f"route '{event_type}' required_fields must be a list")
        static_attributes = route.get("static_attributes", {}) or {}
        if not isinstance(static_attributes, dict):
            raise error_cls(
                f"route '{event_type}' static_attributes must be an object"
            )
        risk_attributes_raw = route.get("risk_attributes", {}) or {}
        if not isinstance(risk_attributes_raw, dict):
            raise error_cls(f"route '{event_type}' risk_attributes must be an object")
        context_fields_raw = route.get("context_fields", {}) or {}
        if not isinstance(context_fields_raw, dict):
            raise error_cls(f"route '{event_type}' context_fields must be an object")
        metadata_fields_raw = route.get("metadata_fields", {}) or {}
        if not isinstance(metadata_fields_raw, dict):
            raise error_cls(f"route '{event_type}' metadata_fields must be an object")
        required_metadata_fields_raw = route.get("required_metadata_fields", []) or []
        if not isinstance(required_metadata_fields_raw, list):
            raise error_cls(
                f"route '{event_type}' required_metadata_fields must be a list"
            )
        external_to_internal_state_raw = route.get("external_to_internal_state", {}) or {}
        if not isinstance(external_to_internal_state_raw, dict):
            raise error_cls(
                f"route '{event_type}' external_to_internal_state must be an object"
            )
        internal_to_external_state_raw = route.get("internal_to_external_state", {}) or {}
        if not isinstance(internal_to_external_state_raw, dict):
            raise error_cls(
                f"route '{event_type}' internal_to_external_state must be an object"
            )
        allowed_state_transitions_raw = route.get("allowed_state_transitions", {}) or {}
        if not isinstance(allowed_state_transitions_raw, dict):
            raise error_cls(
                f"route '{event_type}' allowed_state_transitions must be an object"
            )
        if any(not isinstance(v, list) for v in allowed_state_transitions_raw.values()):
            raise error_cls(
                f"route '{event_type}' allowed_state_transitions values must be lists"
            )
        routes[event_type] = ApprovalEventRoute(
            action_type=str(route["action_type"]),
            actor_id_path=str(route["actor_id_path"]),
            attributes={str(k): str(v) for k, v in attrs.items()},
            required_fields=[str(item) for item in required_fields],
            static_attributes=static_attributes,
            payload_path=route.get("payload_path"),
            request_id_path=route.get("request_id_path"),
            actor_role_path=route.get("actor_role_path"),
            source_record_id_path=route.get("source_record_id_path"),
            policy_bundle=route.get("policy_bundle"),
            source_object_type_path=route.get("source_object_type_path"),
            workflow_stage_path=route.get("workflow_stage_path"),
            requested_action_path=route.get("requested_action_path"),
            correlation_key_path=route.get("correlation_key_path"),
            idempotency_key_path=route.get("idempotency_key_path"),
            risk_attributes={
                str(k): str(v)
                for k, v in risk_attributes_raw.items()
            },
            evidence_references_path=route.get("evidence_references_path"),
            static_source_object_type=route.get("static_source_object_type"),
            static_workflow_stage=route.get("static_workflow_stage"),
            static_requested_action=route.get("static_requested_action"),
            external_state_path=route.get("external_state_path"),
            previous_external_state_path=route.get("previous_external_state_path"),
            external_to_internal_state={
                str(k): str(v) for k, v in external_to_internal_state_raw.items()
            },
            internal_to_external_state={
                str(k): str(v) for k, v in internal_to_external_state_raw.items()
            },
            allowed_state_transitions={
                str(k): [str(item) for item in v]
                for k, v in allowed_state_transitions_raw.items()
            },
            context_fields={
                str(k): str(v) for k, v in context_fields_raw.items()
            },
            metadata_fields={
                str(k): str(v) for k, v in metadata_fields_raw.items()
            },
            required_metadata_fields=[
                str(item) for item in required_metadata_fields_raw
            ],
            sla_deadline_path=route.get("sla_deadline_path"),
            escalation_deadline_path=route.get("escalation_deadline_path"),
        )
    return routes


class ApprovalConnectorBase(Connector):
    """Shared inbound normalization pipeline for enterprise approval connectors."""

    invalid_envelope_message: str
    error_cls: type[IntegrationError]
    source_system: str

    def __init__(
        self,
        *,
        config: ApprovalConnectorConfig,
        verifier: ApprovalWebhookVerifier,
        idempotency_store: DeliveryIdempotencyStore,
        reliability_observer: ConnectorReliabilityObserver | None = None,
    ) -> None:
        self._config = config
        self._verifier = verifier
        self._idempotency = idempotency_store
        self._reliability_observer = reliability_observer

    def handle_event(self, event: dict[str, Any]) -> dict[str, Any]:
        headers = event.get("headers") or {}
        payload = event.get("payload") or {}
        raw_body = event.get("raw_body") or b""
        if (
            not isinstance(headers, dict)
            or not isinstance(payload, dict)
            or not isinstance(raw_body, bytes)
        ):
            raise self.error_cls(self.invalid_envelope_message)
        normalized = self.normalize_event(headers=headers, payload=payload, raw_body=raw_body)
        canonical_replay_payload = normalized.canonical_replay_payload()
        operational_metadata = normalized.operational_metadata()
        canonical_replay_payload_hash = hashlib.sha256(
            json.dumps(
                canonical_replay_payload, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        return {
            "normalized_event": normalized.model_dump(),
            "canonical_replay_payload": canonical_replay_payload,
            "operational_metadata": operational_metadata,
            "determinism_contract": {
                "scope": "canonical_replay_payload_only",
                "canonical_replay_payload": canonical_replay_payload,
                "operational_metadata": operational_metadata,
                "canonical_replay_payload_hash": canonical_replay_payload_hash,
            },
            "action_proposal": self.map_to_proposal(normalized),
        }

    def normalize_event(
        self,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        raw_body: bytes,
    ) -> NormalizedApprovalEvent:
        lowered_headers = {str(k).lower(): str(v) for k, v in headers.items()}
        self._verifier.verify(headers=lowered_headers, raw_body=raw_body)
        event_type = self.extract_event_type(payload)
        route = self._config.routes.get(event_type)
        if route is None:
            raise self.error_cls(
                f"unsupported {self.source_system} event type '{event_type}'"
            )
        delivery_id = self.compute_delivery_id(
            headers=lowered_headers,
            payload=payload,
            event_type=event_type,
            route=route,
        )
        normalized = self.build_normalized_event(
            payload=payload, event_type=event_type, route=route, delivery_id=delivery_id
        )
        replay_fingerprint = hashlib.sha256(
            json.dumps(
                normalized.canonical_replay_payload(),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        idempotency_result = self._idempotency.mark_if_new(
            delivery_id,
            payload_fingerprint=replay_fingerprint,
        )
        if idempotency_result == "duplicate":
            if self._reliability_observer is not None:
                self._reliability_observer.record_inbound_duplicate_suppression()
            logger.warning(
                "connector_inbound_duplicate_suppressed",
                connector=self.source_system,
                delivery_id=delivery_id,
            )
            raise self.error_cls(f"duplicate delivery '{delivery_id}'")
        if idempotency_result == "conflict":
            logger.warning(
                "connector_inbound_idempotency_conflict",
                connector=self.source_system,
                delivery_id=delivery_id,
            )
            raise self.error_cls(
                f"idempotency payload conflict for delivery '{delivery_id}'"
            )
        return normalized

    def map_to_proposal(self, event: NormalizedApprovalEvent) -> ActionProposal:
        route = self._config.routes[event.source_event_type]
        return to_action_proposal(event, route)

    def route_for_event_type(self, event_type: str) -> ApprovalEventRoute | None:
        return self._config.routes.get(event_type)

    def extract_event_type(self, payload: dict[str, Any]) -> str:
        raise NotImplementedError

    def compute_delivery_id(
        self,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        event_type: str,
        route: ApprovalEventRoute,
    ) -> str:
        raise NotImplementedError

    def build_normalized_event(
        self,
        *,
        payload: dict[str, Any],
        event_type: str,
        route: ApprovalEventRoute,
        delivery_id: str,
    ) -> NormalizedApprovalEvent:
        raise NotImplementedError

def resolve_path(
    payload: dict[str, Any], path: str, *, error_cls: type[IntegrationError]
) -> Any:
    current: Any = payload
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        raise error_cls(f"missing required field path '{path}'")
    return current


def to_action_proposal(
    event: NormalizedApprovalEvent, route: ApprovalEventRoute
) -> ActionProposal:
    attrs = {
        **event.attributes,
        "source_system": event.source_system,
        "source_event_type": event.source_event_type,
        "source_object_type": event.source_object_type,
        "source_object_id": event.source_object_id,
        "workflow_stage": event.workflow_stage,
        "requested_action": event.requested_action,
        "correlation_key": event.correlation_key,
        "idempotency_key": event.idempotency_key,
        "risk_attributes": event.risk_attributes,
        "evidence_references": event.evidence_references,
        "external_state": event.external_state,
        "sla_deadline_at": event.sla_deadline_at,
        "escalation_deadline_at": event.escalation_deadline_at,
        **event.source_metadata,
    }
    return ActionProposal(
        action_type=route.action_type,
        request_id=event.request_id,
        actor_id=event.actor.actor_id,
        actor_role=event.actor.actor_role,
        attributes=attrs,
        action_origin=ActionOrigin.AUTONOMOUS_TOOL,
        autonomous_metadata=AutonomousToolMetadata(
            tool_name=event.source_system,
            trigger_type=event.source_event_type,
            trigger_reference=event.source_object_id,
            supervising_owner=event.actor.actor_id,
        ),
    )


def build_normalized_approval_event(
    *,
    payload: dict[str, Any],
    route: ApprovalEventRoute,
    source_event_type: str,
    idempotency_key: str,
    source_system: str,
    default_request_id: str,
    default_source_record_id: str,
    error_cls: type[IntegrationError],
    source_metadata: dict[str, Any] | None = None,
    default_source_object_type: str,
    default_workflow_stage: str,
    default_requested_action: str,
    default_correlation_key: str,
) -> NormalizedApprovalEvent:
    missing: list[str] = []
    for required in route.required_fields:
        try:
            resolve_path(payload, required, error_cls=error_cls)
        except IntegrationError:
            missing.append(required)
    if missing:
        raise error_cls(f"missing required fields: {','.join(missing)}")

    actor_id = str(
        resolve_path(payload, route.actor_id_path, error_cls=error_cls) or ""
    ).strip()
    if not actor_id:
        raise error_cls("missing actor identity")

    actor_role: str | None = None
    if route.actor_role_path:
        actor_role = (
            str(
                resolve_path(payload, route.actor_role_path, error_cls=error_cls) or ""
            ).strip()
            or None
        )

    request_id = default_request_id
    if route.request_id_path:
        request_id = str(
            resolve_path(payload, route.request_id_path, error_cls=error_cls)
        )

    source_object_id = default_source_record_id
    if route.source_record_id_path:
        source_object_id = str(
            resolve_path(payload, route.source_record_id_path, error_cls=error_cls)
        )

    source_object_type = route.static_source_object_type or default_source_object_type
    if route.source_object_type_path:
        source_object_type = str(
            resolve_path(payload, route.source_object_type_path, error_cls=error_cls)
        )

    external_state: str | None = None
    if route.external_state_path:
        external_state = str(
            resolve_path(payload, route.external_state_path, error_cls=error_cls)
        )

    previous_external_state: str | None = None
    if route.previous_external_state_path:
        previous_external_state = str(
            resolve_path(payload, route.previous_external_state_path, error_cls=error_cls)
        )

    workflow_stage = route.static_workflow_stage or default_workflow_stage
    if route.workflow_stage_path:
        workflow_stage = str(
            resolve_path(payload, route.workflow_stage_path, error_cls=error_cls)
        )
    if external_state and route.external_to_internal_state:
        mapped_state = route.external_to_internal_state.get(external_state)
        if not mapped_state:
            raise error_cls(f"unmapped external state '{external_state}'")
        workflow_stage = mapped_state
        if previous_external_state and route.allowed_state_transitions:
            previous_internal = route.external_to_internal_state.get(previous_external_state)
            if not previous_internal:
                raise error_cls(f"unmapped previous external state '{previous_external_state}'")
            allowed = route.allowed_state_transitions.get(previous_internal, [])
            if workflow_stage not in allowed:
                raise error_cls(
                    f"invalid transition '{previous_internal}' -> '{workflow_stage}'"
                )

    requested_action = route.static_requested_action or default_requested_action
    if route.requested_action_path:
        requested_action = str(
            resolve_path(payload, route.requested_action_path, error_cls=error_cls)
        )

    correlation_key = default_correlation_key
    if route.correlation_key_path:
        correlation_key = str(
            resolve_path(payload, route.correlation_key_path, error_cls=error_cls)
        )

    event_idempotency_key = idempotency_key
    if route.idempotency_key_path:
        event_idempotency_key = str(
            resolve_path(payload, route.idempotency_key_path, error_cls=error_cls)
        )

    attrs: dict[str, Any] = {}
    for out_key, in_path in route.attributes.items():
        attrs[out_key] = resolve_path(payload, in_path, error_cls=error_cls)
    for out_key, in_path in route.context_fields.items():
        attrs[out_key] = resolve_path(payload, in_path, error_cls=error_cls)
    attrs.update(route.static_attributes)

    risk_attributes: dict[str, Any] = {}
    for out_key, in_path in route.risk_attributes.items():
        risk_attributes[out_key] = resolve_path(payload, in_path, error_cls=error_cls)

    evidence_references: list[str] = []
    if route.evidence_references_path:
        evidence_payload = resolve_path(
            payload, route.evidence_references_path, error_cls=error_cls
        )
        if isinstance(evidence_payload, list):
            evidence_references = [str(item) for item in evidence_payload]
        elif evidence_payload:
            evidence_references = [str(evidence_payload)]

    metadata_values: dict[str, Any] = {}
    for out_key, in_path in route.metadata_fields.items():
        metadata_values[out_key] = resolve_path(payload, in_path, error_cls=error_cls)
    missing_metadata = [
        key
        for key in route.required_metadata_fields
        if not str(metadata_values.get(key, "")).strip()
    ]
    if missing_metadata:
        raise error_cls(f"missing required metadata fields: {','.join(missing_metadata)}")

    sla_deadline_at: str | None = None
    if route.sla_deadline_path:
        sla_deadline_at = str(
            resolve_path(payload, route.sla_deadline_path, error_cls=error_cls)
        )
    escalation_deadline_at: str | None = None
    if route.escalation_deadline_path:
        escalation_deadline_at = str(
            resolve_path(payload, route.escalation_deadline_path, error_cls=error_cls)
        )

    required_normalized = {
        "source_object_type": source_object_type,
        "source_object_id": source_object_id,
        "workflow_stage": workflow_stage,
        "requested_action": requested_action,
        "correlation_key": correlation_key,
        "idempotency_key": event_idempotency_key,
    }
    missing_normalized = [
        key for key, value in required_normalized.items() if not str(value).strip()
    ]
    if missing_normalized:
        raise error_cls(
            f"missing required normalized fields: {','.join(missing_normalized)}"
        )

    combined_metadata = dict(source_metadata or {})
    combined_metadata.update(metadata_values)
    return NormalizedApprovalEvent(
        source_system=source_system,
        source_event_type=source_event_type,
        source_object_type=str(source_object_type),
        source_object_id=str(source_object_id),
        workflow_stage=str(workflow_stage),
        requested_action=str(requested_action),
        actor=NormalizedActor(actor_id=actor_id, actor_role=actor_role),
        request_id=request_id,
        event_timestamp=datetime.now(timezone.utc).isoformat(),
        attributes=attrs,
        risk_attributes=risk_attributes,
        evidence_references=evidence_references,
        correlation_key=str(correlation_key),
        idempotency_key=str(event_idempotency_key),
        external_state=external_state,
        previous_external_state=previous_external_state,
        sla_deadline_at=sla_deadline_at,
        escalation_deadline_at=escalation_deadline_at,
        source_metadata=combined_metadata,
    )
