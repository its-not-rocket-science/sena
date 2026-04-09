from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from sena.core.models import ExceptionScope, PolicyException


@dataclass(frozen=True)
class ExceptionCreateRequest:
    exception_id: str
    action_type: str
    actor: str | None
    attributes: dict[str, Any]
    expiry: datetime
    approver_class: str
    justification: str


class ExceptionService:
    """In-memory governed exception registry.

    Keeps behavior deterministic by using explicit IDs, normalized UTC timestamps,
    and sorted output ordering.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._exceptions: dict[str, PolicyException] = {}

    @staticmethod
    def _normalize_timestamp(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def create(self, request: ExceptionCreateRequest) -> PolicyException:
        if not request.justification.strip():
            raise ValueError("justification is required")
        expiry = self._normalize_timestamp(request.expiry)
        with self._lock:
            if request.exception_id in self._exceptions:
                raise ValueError(f"exception_id already exists: {request.exception_id}")
            created = PolicyException(
                exception_id=request.exception_id,
                scope=ExceptionScope(
                    action_type=request.action_type,
                    actor=request.actor,
                    attributes=dict(request.attributes),
                ),
                expiry=expiry,
                approver_class=request.approver_class,
                justification=request.justification,
            )
            self._exceptions[created.exception_id] = created
            return created

    def approve(
        self,
        *,
        exception_id: str,
        approver_role: str,
        approver_id: str,
        approved_at: datetime | None = None,
    ) -> PolicyException:
        with self._lock:
            current = self._exceptions.get(exception_id)
            if current is None:
                raise ValueError(f"unknown exception_id: {exception_id}")
            if current.approver_class != approver_role:
                raise ValueError(
                    "approver role does not satisfy approver_class: "
                    f"required={current.approver_class} got={approver_role}"
                )
            stamped_at = self._normalize_timestamp(approved_at or datetime.now(timezone.utc))
            updated = PolicyException(
                exception_id=current.exception_id,
                scope=current.scope,
                expiry=current.expiry,
                approver_class=current.approver_class,
                justification=current.justification,
                approved_by=approver_id,
                approved_at=stamped_at,
            )
            self._exceptions[exception_id] = updated
            return updated

    def list_active(self, now: datetime | None = None) -> list[PolicyException]:
        current_time = self._normalize_timestamp(now or datetime.now(timezone.utc))
        with self._lock:
            active = [
                item
                for item in self._exceptions.values()
                if item.approved_at is not None and item.expiry > current_time
            ]
            return sorted(active, key=lambda item: item.exception_id)

    def list_all(self) -> list[PolicyException]:
        with self._lock:
            return sorted(self._exceptions.values(), key=lambda item: item.exception_id)
