from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sena.audit.chain import append_audit_record, verify_audit_chain


@dataclass(frozen=True)
class AuditService:
    """Application-facing audit helpers and startup hooks."""

    sink_path: str | None = None

    def append_record(self, record: dict[str, Any]) -> dict[str, Any] | None:
        if self.sink_path is None:
            return None
        return append_audit_record(self.sink_path, record)

    def verify_chain(self, sink_path: str | None = None) -> dict[str, Any]:
        target = sink_path or self.sink_path
        if target is None:
            return {"valid": False, "error": "audit sink not configured", "records": 0}
        return verify_audit_chain(target)

    def startup_validate(self) -> dict[str, Any]:
        """Future hook for startup chain checks; currently pass-through when configured."""
        if self.sink_path is None:
            return {"status": "skipped", "reason": "audit sink not configured"}
        return {"status": "ready", "sink": self.sink_path}

    def restore_from_sink(self) -> dict[str, Any]:
        """Future hook for restoring state from audit sinks."""
        if self.sink_path is None:
            return {"status": "skipped", "reason": "audit sink not configured"}
        return {"status": "not_implemented", "sink": self.sink_path}
