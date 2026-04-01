from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from pydantic import BaseModel, Field

from sena.core.models import ActionProposal
from sena.integrations.base import IntegrationError


@dataclass(frozen=True)
class ApprovalEventRoute:
    action_type: str
    actor_id_path: str
    attributes: dict[str, str]
    required_fields: list[str] = field(default_factory=list)
    static_attributes: dict[str, Any] = field(default_factory=dict)
    request_id_path: str | None = None
    actor_role_path: str | None = None
    source_record_id_path: str | None = None
    policy_bundle: str | None = None


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


class NormalizedApprovalEvent(BaseModel):
    delivery_id: str
    source_system: str
    event_type: str
    source_record_id: str
    request_id: str
    actor_id: str
    actor_role: str | None = None
    event_timestamp: str
    attributes: dict[str, Any] = Field(default_factory=dict)
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
        "source_event_type": event.event_type,
        "source_delivery_id": event.delivery_id,
        "source_record_id": event.source_record_id,
        **event.source_metadata,
    }
    return ActionProposal(
        action_type=route.action_type,
        request_id=event.request_id,
        actor_id=event.actor_id,
        actor_role=event.actor_role,
        attributes=attrs,
    )


def build_normalized_approval_event(
    *,
    payload: dict[str, Any],
    route: ApprovalEventRoute,
    event_type: str,
    delivery_id: str,
    source_system: str,
    default_request_id: str,
    default_source_record_id: str,
    error_cls: type[IntegrationError],
    source_metadata: dict[str, Any] | None = None,
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

    source_record_id = default_source_record_id
    if route.source_record_id_path:
        source_record_id = str(resolve_path(payload, route.source_record_id_path, error_cls=error_cls))

    attrs: dict[str, Any] = {}
    for out_key, in_path in route.attributes.items():
        attrs[out_key] = resolve_path(payload, in_path, error_cls=error_cls)
    attrs.update(route.static_attributes)

    return NormalizedApprovalEvent(
        delivery_id=delivery_id,
        source_system=source_system,
        event_type=event_type,
        source_record_id=source_record_id,
        request_id=request_id,
        actor_id=actor_id,
        actor_role=actor_role,
        event_timestamp=datetime.now(timezone.utc).isoformat(),
        attributes=attrs,
        source_metadata=source_metadata or {},
    )
