from __future__ import annotations

import hashlib
import json
from typing import Any

from sena.audit.sinks import AuditSink, JsonlFileAuditSink


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_chain_hash(record: dict[str, Any], previous_chain_hash: str | None) -> str:
    material = {
        "previous_chain_hash": previous_chain_hash,
        "record": record,
    }
    return hashlib.sha256(_canonical_json(material).encode("utf-8")).hexdigest()


def _resolve_sink(path_or_sink: str | AuditSink) -> AuditSink:
    if isinstance(path_or_sink, str):
        return JsonlFileAuditSink(path=path_or_sink)
    return path_or_sink


def append_audit_record(path_or_sink: str | AuditSink, record: dict[str, Any]) -> dict[str, Any]:
    sink = _resolve_sink(path_or_sink)

    previous_chain_hash = None
    records = sink.load_records()
    if records:
        previous_chain_hash = records[-1]["chain_hash"]

    chain_hash = compute_chain_hash(record, previous_chain_hash)
    payload = {
        **record,
        "previous_chain_hash": previous_chain_hash,
        "chain_hash": chain_hash,
    }
    sink.append(payload)
    return payload


def verify_audit_chain(path_or_sink: str | AuditSink) -> dict[str, Any]:
    sink = _resolve_sink(path_or_sink)
    rows = sink.load_records()
    if not rows:
        if isinstance(path_or_sink, str):
            return {
                "valid": False,
                "error": f"audit file not found or empty: {path_or_sink}",
                "records": 0,
            }
        return {"valid": False, "error": "no audit records found", "records": 0}

    previous_chain_hash = None
    count = 0
    for row in rows:
        count += 1
        claimed_previous = row.get("previous_chain_hash")
        if claimed_previous != previous_chain_hash:
            return {
                "valid": False,
                "error": f"record {count}: previous_chain_hash mismatch",
                "records": count,
            }
        current_hash = row.get("chain_hash")
        record = {
            k: v for k, v in row.items() if k not in {"chain_hash", "previous_chain_hash"}
        }
        expected_hash = compute_chain_hash(record, previous_chain_hash)
        if expected_hash != current_hash:
            return {
                "valid": False,
                "error": f"record {count}: chain_hash mismatch",
                "records": count,
            }
        previous_chain_hash = current_hash

    return {"valid": True, "records": count, "head": previous_chain_hash}
