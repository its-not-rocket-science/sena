from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sena.audit.evidentiary import (
    AuditRecordSigner,
    AuditRecordVerifier,
    attach_evidentiary_fields,
    verify_signature,
)
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


def append_audit_record(
    path_or_sink: str | AuditSink,
    record: dict[str, Any],
    signer: AuditRecordSigner | None = None,
) -> dict[str, Any]:
    sink = _resolve_sink(path_or_sink)

    payload = dict(record)
    if signer is not None:
        payload = attach_evidentiary_fields(payload, signer)

    if hasattr(sink, "append_chained"):
        return sink.append_chained(payload, compute_chain_hash)

    previous_chain_hash = None
    records = sink.load_records()
    if records:
        previous_chain_hash = records[-1]["chain_hash"]

    payload["previous_chain_hash"] = previous_chain_hash
    payload["chain_hash"] = compute_chain_hash(payload, previous_chain_hash)
    sink.append(payload)
    return payload


def _diagnostic(
    *,
    category: str,
    message: str,
    record_index: int | None = None,
    location: str | None = None,
    remediation: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "category": category,
        "message": message,
    }
    if record_index is not None:
        payload["record_index"] = record_index
    if location:
        payload["location"] = location
    if remediation:
        payload["remediation"] = remediation
    return payload


def _diagnostic_to_error(diag: dict[str, Any]) -> str:
    record_index = diag.get("record_index")
    location = diag.get("location")
    prefix = "audit"
    if isinstance(record_index, int):
        prefix = f"record {record_index}"
        if location:
            prefix = f"{prefix} ({location})"
    elif isinstance(location, str):
        prefix = f"audit ({location})"
    return f"{prefix}: [{diag['category']}] {diag['message']}"


def _issue_to_diagnostic(issue: str) -> dict[str, Any]:
    parts = issue.split(":")
    code = parts[0]
    location: str | None = None
    if code == "malformed_record" and len(parts) >= 3:
        location = f"{parts[1]}:{parts[2]}"
    elif len(parts) > 1 and ".jsonl" in parts[1]:
        location = parts[1]

    issue_map = {
        "missing_segment": (
            "manifest_segment_missing",
            "Restore the missing rotated segment or repair the manifest before trusting this chain.",
        ),
        "malformed_record": (
            "record_malformed_json",
            "Restore from backup and inspect the segment line offset for truncation or partial writes.",
        ),
        "segment_record_count_mismatch": (
            "manifest_segment_record_count_mismatch",
            "Reconcile manifest metadata with on-disk records; do not rewrite records in place.",
        ),
        "segment_first_sequence_mismatch": (
            "manifest_segment_first_sequence_mismatch",
            "Validate rotated segment boundaries and restore manifest/segments from the same backup set.",
        ),
        "segment_last_sequence_mismatch": (
            "manifest_segment_last_sequence_mismatch",
            "Validate rotated segment boundaries and restore manifest/segments from the same backup set.",
        ),
        "segment_sequence_gap": (
            "segment_sequence_gap",
            "A sequence gap indicates record loss or segment divergence; recover missing segment(s) before continuing.",
        ),
        "orphaned_segment": (
            "orphaned_segment_file",
            "Either attach orphaned segment files to the manifest or quarantine them for forensic review.",
        ),
        "manifest_next_sequence_mismatch": (
            "manifest_next_sequence_mismatch",
            "Regenerate or restore the manifest from a trusted backup; next_sequence must match record inventory.",
        ),
    }

    category, remediation = issue_map.get(
        code,
        (
            "sink_issue",
            "Inspect sink metadata and rotated segment files for divergence.",
        ),
    )
    message = issue
    if location:
        message = f"{code} detected at {location}"
    return _diagnostic(
        category=category,
        message=message,
        location=location,
        remediation=remediation,
    )


def verify_audit_chain(
    path_or_sink: str | AuditSink, verifier: AuditRecordVerifier | None = None
) -> dict[str, Any]:
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
    diagnostics: list[dict[str, Any]] = []
    seen_decision_ids: set[str] = set()
    seen_storage_sequence_numbers: set[int] = set()
    for row in rows:
        count += 1
        location = _row_location(details, count)
        claimed_previous = row.get("previous_chain_hash")
        if claimed_previous != previous_chain_hash:
            diagnostics.append(
                _diagnostic(
                    category="chain_link_mismatch",
                    message=(
                        "previous_chain_hash mismatch "
                        f"(expected={previous_chain_hash}, actual={claimed_previous})"
                    ),
                    record_index=count,
                    location=location,
                    remediation=(
                        "Restore from a trusted backup or compare this record with upstream exported evidence."
                    ),
                )
            )

        if "storage_sequence_number" in row:
            seq = row.get("storage_sequence_number")
            if isinstance(seq, int) and seq in seen_storage_sequence_numbers:
                diagnostics.append(
                    _diagnostic(
                        category="duplicate_storage_sequence_number",
                        message=f"duplicate storage sequence number ({seq})",
                        record_index=count,
                        location=location,
                        remediation="Duplicate storage sequence numbers indicate replay/rewrite tampering; stop ingestion and investigate segment history.",
                    )
                )
            if (
                previous_seq is not None
                and isinstance(seq, int)
                and seq != previous_seq + 1
            ):
                diagnostics.append(
                    _diagnostic(
                        category="storage_sequence_gap",
                        message=f"storage sequence gap (previous={previous_seq}, current={seq})",
                        record_index=count,
                        location=location,
                        remediation="Locate missing records between sequence numbers and restore complete segment set before continuing.",
                    )
                )
            if isinstance(seq, int):
                previous_seq = seq
                seen_storage_sequence_numbers.add(seq)

        decision_id = row.get("decision_id")
        if isinstance(decision_id, str) and decision_id:
            if decision_id in seen_decision_ids:
                diagnostics.append(
                    _diagnostic(
                        category="duplicate_decision_id",
                        message=f"duplicate decision_id ({decision_id})",
                        record_index=count,
                        location=location,
                        remediation="Each decision_id must be globally unique; inspect producer idempotency keys and replay handling.",
                    )
                )
            seen_decision_ids.add(decision_id)

        has_signature_fields = any(
            key in row
            for key in (
                "signature",
                "signing_key_id",
                "signed_timestamp_hash",
                "signer_identity",
            )
        )
        if has_signature_fields:
            if verifier is None:
                diagnostics.append(
                    _diagnostic(
                        category="signature_present_but_no_verifier",
                        message="signature fields present but no verifier was provided",
                        record_index=count,
                        location=location,
                        remediation="Re-run verification with --keyring or configure an AuditRecordVerifier.",
                    )
                )
            else:
                signature_ok, signature_error = verify_signature(row, verifier)
                if not signature_ok:
                    diagnostics.append(
                        _diagnostic(
                            category="signature_verification_failed",
                            message=f"signature verification failed: {signature_error}",
                            record_index=count,
                            location=location,
                            remediation="Check key rotation/keyring completeness and confirm signature metadata was not altered.",
                        )
                    )

        current_hash = row.get("chain_hash")
        record = {k: v for k, v in row.items() if k not in {"chain_hash"}}
        expected_hash = compute_chain_hash(record, previous_chain_hash)
        if expected_hash != current_hash:
            diagnostics.append(
                _diagnostic(
                    category="chain_hash_mismatch",
                    message=f"chain_hash mismatch (expected={expected_hash}, actual={current_hash})",
                    record_index=count,
                    location=location,
                    remediation="Do not recompute hashes in place. Recover the original record from immutable backup evidence.",
                )
            )
        previous_chain_hash = current_hash

    if details and details.get("issues"):
        diagnostics.extend(_issue_to_diagnostic(issue) for issue in details["issues"])

    if diagnostics:
        payload: dict[str, Any] = {
            "valid": False,
            "records": count,
            "errors": [_diagnostic_to_error(diag) for diag in diagnostics],
            "diagnostics": diagnostics,
        }
        if details:
            payload["segments"] = details.get("segments", [])
        return payload

    result: dict[str, Any] = {
        "valid": True,
        "records": count,
        "head": previous_chain_hash,
    }
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
        if one_based_record_index <= cursor + segment_count:
            offset = one_based_record_index - cursor
            return f"{segment.get('file', 'unknown')}#{offset}"
        cursor += segment_count
    return "unknown"


def summarize_audit_chain(path_or_sink: str | AuditSink) -> dict[str, Any]:
    verification = verify_audit_chain(path_or_sink)
    sink = _resolve_sink(path_or_sink)
    details = (
        sink.load_records_detailed()
        if hasattr(sink, "load_records_detailed")
        else {"segments": []}
    )
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
        "manifest_path": str(
            Path(path_or_sink).with_name(f"{Path(path_or_sink).name}.manifest.json")
        )
        if isinstance(path_or_sink, str)
        else None,
        "next_sequence": manifest.get("next_sequence"),
        "first_decision_id": first_decision,
        "last_decision_id": last_decision,
        "errors": verification.get("errors", []),
    }


def locate_decision_in_audit(
    path_or_sink: str | AuditSink, decision_id: str
) -> dict[str, Any]:
    sink = _resolve_sink(path_or_sink)
    details = (
        sink.load_records_detailed()
        if hasattr(sink, "load_records_detailed")
        else {"records": []}
    )
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
