from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sena.audit.chain import append_audit_record, verify_audit_chain
from sena.audit.legal_hold import LegalHoldStore, hold_store_from_audit_path
from sena.audit.merkle import build_merkle_tree, get_proof, verify_proof
from sena.audit.storage import AuditStorage, storage_from_env


@dataclass
class AuditService:
    """Application-facing audit helpers and startup hooks."""

    sink_path: str | None = None
    storage: AuditStorage | None = None
    hold_store: LegalHoldStore | None = None

    def __post_init__(self) -> None:
        if self.storage is None:
            self.storage = storage_from_env(self.sink_path)
        if self.hold_store is None:
            self.hold_store = hold_store_from_audit_path(self.sink_path)

    def append_record(self, record: dict[str, Any]) -> dict[str, Any] | None:
        if self.sink_path is None and self.storage is None:
            return None

        if self.storage is not None:
            payload = dict(record)
            entry_id = self.storage.append(payload)
            try:
                return self.storage.read(entry_id)
            except Exception:
                payload["storage_entry_id"] = entry_id
                return payload

        if self.sink_path is None:
            return None
        return append_audit_record(self.sink_path, record)

    def verify_chain(self, sink_path: str | None = None) -> dict[str, Any]:
        target = sink_path or self.sink_path
        if target is None:
            return {"valid": False, "error": "audit sink not configured", "records": 0}
        return verify_audit_chain(target)

    def verify_storage_immutable(self) -> bool:
        if self.storage is None:
            return False
        return self.storage.verify_immutable()

    def place_legal_hold(self, decision_id: str, reason: str | None = None) -> dict[str, Any]:
        if self.hold_store is None:
            raise RuntimeError("audit hold store not configured")
        return self.hold_store.create_hold(decision_id=decision_id, reason=reason)

    def list_legal_holds(self) -> list[dict[str, Any]]:
        if self.hold_store is None:
            return []
        return self.hold_store.list_holds()

    def verify_decision_merkle_proof(
        self, decision_id: str, merkle_proof: list[str], expected_root: str
    ) -> dict[str, Any]:
        if self.sink_path is None:
            return {
                "valid": False,
                "error": "audit sink not configured",
                "decision_id": decision_id,
            }

        from sena.audit.sinks import JsonlFileAuditSink

        sink = JsonlFileAuditSink(path=self.sink_path)
        details = sink.load_records_detailed()
        records = details.get("records", [])
        if not records:
            return {
                "valid": False,
                "error": "no audit records found",
                "decision_id": decision_id,
            }

        matching_index = None
        for index, row in enumerate(records):
            if str(row.get("decision_id")) == decision_id:
                matching_index = index
                break

        if matching_index is None:
            return {
                "valid": False,
                "error": "decision not found",
                "decision_id": decision_id,
            }

        tree = build_merkle_tree(records)
        canonical_proof = get_proof(tree, matching_index)
        entry = records[matching_index]
        computed_root = tree.root
        proof_valid = verify_proof(entry, merkle_proof, expected_root)

        return {
            "valid": proof_valid,
            "decision_id": decision_id,
            "record_index": matching_index + 1,
            "computed_root": computed_root,
            "expected_root": expected_root,
            "proof_length": len(merkle_proof),
            "canonical_proof": canonical_proof,
            "proof_matches_canonical": merkle_proof == canonical_proof,
        }

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
