from __future__ import annotations

import json
from pathlib import Path

from sena.audit.chain import append_audit_record, compute_chain_hash, verify_audit_chain
from sena.audit.sinks import JsonlFileAuditSink, RotationPolicy


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(item, sort_keys=True) for item in rows) + "\n", encoding="utf-8")


def test_audit_chain_detects_record_deletion(tmp_path) -> None:
    sink = tmp_path / "audit.jsonl"
    append_audit_record(str(sink), {"decision_id": "delete-1", "outcome": "APPROVED"})
    append_audit_record(str(sink), {"decision_id": "delete-2", "outcome": "BLOCKED"})
    append_audit_record(str(sink), {"decision_id": "delete-3", "outcome": "APPROVED"})

    rows = _read_jsonl(sink)
    _write_jsonl(sink, [rows[0], rows[2]])

    result = verify_audit_chain(str(sink))
    assert result["valid"] is False
    assert any(diag["category"] == "chain_link_mismatch" for diag in result["diagnostics"])


def test_audit_chain_detects_reordering(tmp_path) -> None:
    sink = tmp_path / "audit.jsonl"
    append_audit_record(str(sink), {"decision_id": "reorder-1", "outcome": "APPROVED"})
    append_audit_record(str(sink), {"decision_id": "reorder-2", "outcome": "BLOCKED"})
    append_audit_record(str(sink), {"decision_id": "reorder-3", "outcome": "APPROVED"})

    rows = _read_jsonl(sink)
    _write_jsonl(sink, [rows[0], rows[2], rows[1]])

    result = verify_audit_chain(str(sink))
    assert result["valid"] is False
    assert any(diag["category"] == "chain_link_mismatch" for diag in result["diagnostics"])


def test_audit_chain_detects_recomputed_hash_after_payload_tamper(tmp_path) -> None:
    sink = tmp_path / "audit.jsonl"
    append_audit_record(str(sink), {"decision_id": "tamper-1", "outcome": "APPROVED"})
    append_audit_record(str(sink), {"decision_id": "tamper-2", "outcome": "BLOCKED"})

    rows = _read_jsonl(sink)
    first, second = rows
    second["decision_id"] = "tamper-1"
    second["chain_hash"] = compute_chain_hash(
        {k: v for k, v in second.items() if k != "chain_hash"},
        second.get("previous_chain_hash"),
    )
    _write_jsonl(sink, [first, second])

    result = verify_audit_chain(str(sink))
    assert result["valid"] is False
    assert any(diag["category"] == "duplicate_decision_id" for diag in result["diagnostics"])


def test_audit_chain_detects_sequence_gap_across_rotated_segments(tmp_path) -> None:
    sink = JsonlFileAuditSink(
        path=str(tmp_path / "audit.jsonl"), rotation=RotationPolicy(max_file_bytes=250)
    )
    for i in range(5):
        append_audit_record(sink, {"decision_id": f"seg-gap-{i}", "outcome": "APPROVED"})

    manifest_path = tmp_path / "audit.jsonl.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    first_segment = tmp_path / manifest["segments"][0]["file"]
    rows = _read_jsonl(first_segment)
    rows[0]["storage_sequence_number"] = 999
    rows[0]["chain_hash"] = compute_chain_hash(
        {k: v for k, v in rows[0].items() if k != "chain_hash"},
        rows[0].get("previous_chain_hash"),
    )
    _write_jsonl(first_segment, rows)

    result = verify_audit_chain(sink)
    assert result["valid"] is False
    assert any(diag["category"] == "segment_sequence_gap" for diag in result["diagnostics"])


def test_audit_chain_detects_manifest_segment_divergence(tmp_path) -> None:
    sink = JsonlFileAuditSink(
        path=str(tmp_path / "audit.jsonl"), rotation=RotationPolicy(max_file_bytes=250)
    )
    for i in range(4):
        append_audit_record(sink, {"decision_id": f"manifest-div-{i}", "outcome": "APPROVED"})

    manifest_path = tmp_path / "audit.jsonl.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["segments"][0]["record_count"] += 2
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8")

    result = verify_audit_chain(sink)
    assert result["valid"] is False
    assert any(
        diag["category"] == "manifest_segment_record_count_mismatch"
        for diag in result["diagnostics"]
    )


def test_audit_chain_diagnostics_include_location_and_remediation(tmp_path) -> None:
    sink = tmp_path / "audit.jsonl"
    append_audit_record(str(sink), {"decision_id": "d1", "outcome": "APPROVED"})

    rows = _read_jsonl(sink)
    rows.append({"decision_id": "d1", "signature": "abc", "chain_hash": "bad"})
    _write_jsonl(sink, rows)

    result = verify_audit_chain(str(sink))
    assert result["valid"] is False
    assert result["diagnostics"]
    first = result["diagnostics"][0]
    assert "category" in first
    assert "message" in first
    assert "remediation" in first
    assert "location" in first


def test_audit_chain_detects_partial_file_corruption_with_precise_location(tmp_path) -> None:
    sink = tmp_path / "audit.jsonl"
    append_audit_record(str(sink), {"decision_id": "good-1", "outcome": "APPROVED"})
    with sink.open("a", encoding="utf-8") as handle:
        handle.write('{"decision_id":"broken"')

    result = verify_audit_chain(str(sink))
    assert result["valid"] is False
    malformed = [diag for diag in result["diagnostics"] if diag["category"] == "record_malformed_json"]
    assert malformed
    assert malformed[0]["location"] == "audit.jsonl:2"


def test_audit_chain_detects_signature_without_verifier(tmp_path) -> None:
    sink = tmp_path / "audit.jsonl"
    append_audit_record(str(sink), {"decision_id": "sig-1", "outcome": "APPROVED"})
    rows = _read_jsonl(sink)
    rows[0]["signature"] = "deadbeef"
    _write_jsonl(sink, rows)

    result = verify_audit_chain(str(sink))
    assert result["valid"] is False
    assert any(
        diag["category"] == "signature_present_but_no_verifier"
        for diag in result["diagnostics"]
    )
