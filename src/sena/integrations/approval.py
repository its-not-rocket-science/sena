from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from pydantic import BaseModel, Field

from sena.core.enums import ActionOrigin
from sena.core.models import ActionProposal, AutonomousToolMetadata
from sena.integrations.base import IntegrationError


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


class DeliveryIdempotencyStore(Protocol):
    def mark_if_new(self, delivery_id: str) -> bool: ...


class InMemoryDeliveryIdempotencyStore:
    def __init__(self) -> None:
        self._seen: set[str] = set()

    def mark_if_new(self, delivery_id: str) -> bool:
        if delivery_id in self._seen:
            return False
        self._seen.add(delivery_id)
        return True


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
    source_metadata: dict[str, Any] = Field(default_factory=dict)


def resolve_path(payload: dict[str, Any], path: str, *, error_cls: type[IntegrationError]) -> Any:
    current: Any = payload
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        raise error_cls(f"missing required field path '{path}'")
    return current


def to_action_proposal(event: NormalizedApprovalEvent, route: ApprovalEventRoute) -> ActionProposal:
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

    actor_id = str(resolve_path(payload, route.actor_id_path, error_cls=error_cls) or "").strip()
    if not actor_id:
        raise error_cls("missing actor identity")

    actor_role: str | None = None
    if route.actor_role_path:
        actor_role = str(resolve_path(payload, route.actor_role_path, error_cls=error_cls) or "").strip() or None

    request_id = default_request_id
    if route.request_id_path:
        request_id = str(resolve_path(payload, route.request_id_path, error_cls=error_cls))

    source_object_id = default_source_record_id
    if route.source_record_id_path:
        source_object_id = str(resolve_path(payload, route.source_record_id_path, error_cls=error_cls))

    source_object_type = route.static_source_object_type or default_source_object_type
    if route.source_object_type_path:
        source_object_type = str(resolve_path(payload, route.source_object_type_path, error_cls=error_cls))

    workflow_stage = route.static_workflow_stage or default_workflow_stage
    if route.workflow_stage_path:
        workflow_stage = str(resolve_path(payload, route.workflow_stage_path, error_cls=error_cls))

    requested_action = route.static_requested_action or default_requested_action
    if route.requested_action_path:
        requested_action = str(resolve_path(payload, route.requested_action_path, error_cls=error_cls))

    correlation_key = default_correlation_key
    if route.correlation_key_path:
        correlation_key = str(resolve_path(payload, route.correlation_key_path, error_cls=error_cls))

    event_idempotency_key = idempotency_key
    if route.idempotency_key_path:
        event_idempotency_key = str(resolve_path(payload, route.idempotency_key_path, error_cls=error_cls))

    attrs: dict[str, Any] = {}
    for out_key, in_path in route.attributes.items():
        attrs[out_key] = resolve_path(payload, in_path, error_cls=error_cls)
    attrs.update(route.static_attributes)

    risk_attributes: dict[str, Any] = {}
    for out_key, in_path in route.risk_attributes.items():
        risk_attributes[out_key] = resolve_path(payload, in_path, error_cls=error_cls)

    evidence_references: list[str] = []
    if route.evidence_references_path:
        evidence_payload = resolve_path(payload, route.evidence_references_path, error_cls=error_cls)
        if isinstance(evidence_payload, list):
            evidence_references = [str(item) for item in evidence_payload]
        elif evidence_payload:
            evidence_references = [str(evidence_payload)]

    required_normalized = {
        "source_object_type": source_object_type,
        "source_object_id": source_object_id,
        "workflow_stage": workflow_stage,
        "requested_action": requested_action,
        "correlation_key": correlation_key,
        "idempotency_key": event_idempotency_key,
    }
    missing_normalized = [key for key, value in required_normalized.items() if not str(value).strip()]
    if missing_normalized:
        raise error_cls(f"missing required normalized fields: {','.join(missing_normalized)}")

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
        source_metadata=source_metadata or {},
    )
