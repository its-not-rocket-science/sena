from __future__ import annotations

import hashlib
import json
from pathlib import Path
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

    if hasattr(sink, "append_chained"):
        return sink.append_chained(record, compute_chain_hash)

    previous_chain_hash = None
    records = sink.load_records()
    if records:
        previous_chain_hash = records[-1]["chain_hash"]

    payload = dict(record)
    payload["previous_chain_hash"] = previous_chain_hash
    payload["chain_hash"] = compute_chain_hash(payload, previous_chain_hash)
    sink.append(payload)
    return payload


def verify_audit_chain(path_or_sink: str | AuditSink) -> dict[str, Any]:
    sink = _resolve_sink(path_or_sink)
    details: dict[str, Any] | None = None
    if hasattr(sink, "load_records_detailed"):
        details = sink.load_records_detailed()
        rows = details["records"]
    else:
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
    previous_seq = None
    count = 0
    errors: list[str] = []
    for row in rows:
        count += 1
        location = _row_location(details, count)
        claimed_previous = row.get("previous_chain_hash")
        if claimed_previous != previous_chain_hash:
            errors.append(
                f"record {count} ({location}): previous_chain_hash mismatch "
                f"(expected={previous_chain_hash}, actual={claimed_previous})"
            )

        if "storage_sequence_number" in row:
            seq = row.get("storage_sequence_number")
            if previous_seq is not None and isinstance(seq, int) and seq != previous_seq + 1:
                errors.append(
                    f"record {count} ({location}): storage sequence gap "
                    f"(previous={previous_seq}, current={seq})"
                )
            if isinstance(seq, int):
                previous_seq = seq

        current_hash = row.get("chain_hash")
        record = {k: v for k, v in row.items() if k not in {"chain_hash"}}
        expected_hash = compute_chain_hash(record, previous_chain_hash)
        if expected_hash != current_hash:
            errors.append(
                f"record {count} ({location}): chain_hash mismatch "
                f"(expected={expected_hash}, actual={current_hash})"
            )
        previous_chain_hash = current_hash

    if details and details.get("issues"):
        errors.extend(details["issues"])

    if errors:
        payload: dict[str, Any] = {"valid": False, "records": count, "errors": errors}
        if details:
            payload["segments"] = details.get("segments", [])
        return payload

    result: dict[str, Any] = {"valid": True, "records": count, "head": previous_chain_hash}
    if details:
        result["segments"] = details.get("segments", [])
        manifest = details.get("manifest")
        if isinstance(manifest, dict):
            result["manifest"] = {
                "schema_version": manifest.get("schema_version"),
                "segment_count": len(manifest.get("segments", [])),
                "next_sequence": manifest.get("next_sequence"),
            }
    return result


def _row_location(details: dict[str, Any] | None, one_based_record_index: int) -> str:
    if not details:
        return "unknown"
    cursor = 0
    for segment in details.get("segments", []):
        segment_count = int(segment.get("records", 0))
        if cursor + segment_count >= one_based_record_index:
            offset = one_based_record_index - cursor
            return f"{segment.get('file', 'unknown')}#{offset}"
        cursor += segment_count
    return "unknown"


def summarize_audit_chain(path_or_sink: str | AuditSink) -> dict[str, Any]:
    verification = verify_audit_chain(path_or_sink)
    sink = _resolve_sink(path_or_sink)
    details = sink.load_records_detailed() if hasattr(sink, "load_records_detailed") else {"segments": []}
    manifest = details.get("manifest", {}) if isinstance(details, dict) else {}
    segments = details.get("segments", []) if isinstance(details, dict) else []
    records = details.get("records", []) if isinstance(details, dict) else []
    first_decision = records[0].get("decision_id") if records else None
    last_decision = records[-1].get("decision_id") if records else None
    return {
        "valid": verification.get("valid", False),
        "records": verification.get("records", 0),
        "head": verification.get("head"),
        "segment_count": len(segments),
        "manifest_path": str(Path(path_or_sink).with_name(f"{Path(path_or_sink).name}.manifest.json"))
        if isinstance(path_or_sink, str)
        else None,
        "next_sequence": manifest.get("next_sequence"),
        "first_decision_id": first_decision,
        "last_decision_id": last_decision,
        "errors": verification.get("errors", []),
    }


def locate_decision_in_audit(path_or_sink: str | AuditSink, decision_id: str) -> dict[str, Any]:
    sink = _resolve_sink(path_or_sink)
    details = sink.load_records_detailed() if hasattr(sink, "load_records_detailed") else {"records": []}
    rows = details.get("records", [])
    for idx, row in enumerate(rows, start=1):
        if str(row.get("decision_id")) != decision_id:
            continue
        return {
            "found": True,
            "decision_id": decision_id,
            "record_index": idx,
            "location": _row_location(details, idx),
            "storage_sequence_number": row.get("storage_sequence_number"),
            "chain_hash": row.get("chain_hash"),
            "previous_chain_hash": row.get("previous_chain_hash"),
        }
    return {"found": False, "decision_id": decision_id}
