from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sena.audit.chain import compute_chain_hash
from sena.audit.sinks import JsonlFileAuditSink


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    issues: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                issues.append(f"malformed_record:{path.name}:{idx}")
                continue
            if not isinstance(payload, dict):
                issues.append(f"malformed_record:{path.name}:{idx}")
                continue
            rows.append(payload)
    return rows, issues


def _archive_name(
    base_name: str,
    segment_index: int,
    first_sequence: int | None,
    last_sequence: int | None,
    sha256: str,
) -> str:
    first = 0 if first_sequence is None else first_sequence
    last = 0 if last_sequence is None else last_sequence
    return (
        f"{base_name}.archive.seg-{segment_index:06d}."
        f"seq-{first:09d}-{last:09d}.sha256-{sha256[:16]}.jsonl"
    )


def create_audit_archive(
    audit_path: str, archive_dir: str, *, include_active_segment: bool = True
) -> dict[str, Any]:
    sink = JsonlFileAuditSink(path=audit_path)
    details = sink.load_records_detailed()
    source_manifest = details.get("manifest", {})
    segments = details.get("segments", [])
    parent = Path(audit_path).parent
    base_name = Path(audit_path).name

    output_dir = Path(archive_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    archived_segments: list[dict[str, Any]] = []
    for index, segment in enumerate(segments, start=1):
        if not include_active_segment and not segment.get("rotated", False):
            continue
        source_file = parent / str(segment["file"])
        if not source_file.exists():
            raise FileNotFoundError(f"Cannot archive missing segment: {source_file}")

        rows, issues = _read_jsonl(source_file)
        sha256 = _sha256_file(source_file)
        first_sequence = rows[0].get("storage_sequence_number") if rows else None
        last_sequence = rows[-1].get("storage_sequence_number") if rows else None
        first_chain_hash = rows[0].get("chain_hash") if rows else None
        last_chain_hash = rows[-1].get("chain_hash") if rows else None

        archive_name = _archive_name(
            base_name, index, first_sequence, last_sequence, sha256
        )
        archive_path = output_dir / archive_name
        shutil.copy2(source_file, archive_path)

        archived_segments.append(
            {
                "segment_index": index,
                "source_file": source_file.name,
                "archived_file": archive_name,
                "rotated": bool(segment.get("rotated", False)),
                "record_count": len(rows),
                "bytes": archive_path.stat().st_size,
                "sha256": sha256,
                "first_sequence": first_sequence,
                "last_sequence": last_sequence,
                "first_chain_hash": first_chain_hash,
                "last_chain_hash": last_chain_hash,
                "issues": issues,
            }
        )

    head_hash = (
        details.get("records", [])[-1].get("chain_hash")
        if details.get("records")
        else None
    )
    manifest_payload = {
        "schema_version": "1",
        "archive_type": "sena.audit.local.jsonl",
        "source_audit_path": str(Path(audit_path)),
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "head_hash": head_hash,
        "segment_count": len(archived_segments),
        "source_manifest": source_manifest,
        "segments": archived_segments,
    }
    head_fragment = (head_hash or "empty")[:16]
    manifest_name = f"{base_name}.archive.head-{head_fragment}.manifest.json"
    manifest_path = output_dir / manifest_name
    manifest_path.write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    return {
        "manifest_path": str(manifest_path),
        "segments": len(archived_segments),
        "head_hash": head_hash,
    }


def verify_audit_archive(archive_manifest_path: str) -> dict[str, Any]:
    manifest_path = Path(archive_manifest_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    segments = payload.get("segments", [])
    errors: list[str] = []
    records: list[dict[str, Any]] = []

    previous_chain_hash = None
    previous_sequence = None
    for segment in segments:
        file_path = manifest_path.parent / segment["archived_file"]
        if not file_path.exists():
            errors.append(f"missing_archive_segment:{segment['archived_file']}")
            continue

        actual_sha = _sha256_file(file_path)
        if actual_sha != segment.get("sha256"):
            errors.append(
                f"archive_checksum_mismatch:{segment['archived_file']}:expected={segment.get('sha256')}:actual={actual_sha}"
            )

        segment_rows, issues = _read_jsonl(file_path)
        if issues:
            errors.extend(issues)
        if len(segment_rows) != segment.get("record_count"):
            errors.append(
                f"archive_record_count_mismatch:{segment['archived_file']}:expected={segment.get('record_count')}:actual={len(segment_rows)}"
            )
        records.extend(segment_rows)

        if segment_rows:
            first_sequence = segment_rows[0].get("storage_sequence_number")
            last_sequence = segment_rows[-1].get("storage_sequence_number")
            if first_sequence != segment.get("first_sequence"):
                errors.append(
                    f"archive_first_sequence_mismatch:{segment['archived_file']}:expected={segment.get('first_sequence')}:actual={first_sequence}"
                )
            if last_sequence != segment.get("last_sequence"):
                errors.append(
                    f"archive_last_sequence_mismatch:{segment['archived_file']}:expected={segment.get('last_sequence')}:actual={last_sequence}"
                )

    for idx, row in enumerate(records, start=1):
        claimed_previous = row.get("previous_chain_hash")
        if claimed_previous != previous_chain_hash:
            errors.append(
                f"archive_chain_link_mismatch:record={idx}:expected_previous={previous_chain_hash}:actual_previous={claimed_previous}"
            )
        sequence = row.get("storage_sequence_number")
        if (
            isinstance(sequence, int)
            and previous_sequence is not None
            and sequence != previous_sequence + 1
        ):
            errors.append(
                f"archive_sequence_gap:record={idx}:previous={previous_sequence}:current={sequence}"
            )
        record_for_hash = {k: v for k, v in row.items() if k != "chain_hash"}
        expected_hash = compute_chain_hash(record_for_hash, previous_chain_hash)
        if row.get("chain_hash") != expected_hash:
            errors.append(
                f"archive_chain_hash_mismatch:record={idx}:expected={expected_hash}:actual={row.get('chain_hash')}"
            )
        if isinstance(sequence, int):
            previous_sequence = sequence
        previous_chain_hash = row.get("chain_hash")

    expected_head = payload.get("head_hash")
    if expected_head != previous_chain_hash:
        errors.append(
            f"archive_head_hash_mismatch:expected={expected_head}:actual={previous_chain_hash}"
        )

    return {
        "valid": not errors,
        "records": len(records),
        "segments": len(segments),
        "head": previous_chain_hash,
        "errors": errors,
    }


def restore_audit_archive(
    archive_manifest_path: str, restore_audit_path: str
) -> dict[str, Any]:
    manifest_path = Path(archive_manifest_path)
    archive = json.loads(manifest_path.read_text(encoding="utf-8"))
    verify = verify_audit_archive(archive_manifest_path)
    if not verify["valid"]:
        raise ValueError("Archive verification failed before restore")

    restore_sink = Path(restore_audit_path)
    restore_sink.parent.mkdir(parents=True, exist_ok=True)

    segments_meta: list[dict[str, Any]] = []
    source_manifest = archive.get("source_manifest", {})
    source_segments = (
        source_manifest.get("segments", []) if isinstance(source_manifest, dict) else []
    )

    for idx, segment in enumerate(archive.get("segments", []), start=1):
        src = manifest_path.parent / segment["archived_file"]
        if idx <= len(source_segments):
            target_name = source_segments[idx - 1].get(
                "file", f"{restore_sink.name}.seg-{idx:06d}.jsonl"
            )
            segments_meta.append(dict(source_segments[idx - 1], file=target_name))
        else:
            target_name = restore_sink.name
        target = restore_sink.parent / target_name
        shutil.copy2(src, target)

    if archive.get("segments"):
        last_archived = archive["segments"][-1]
        if not bool(last_archived.get("rotated", False)):
            copied_active = restore_sink.parent / restore_sink.name
            if copied_active.exists() and copied_active.name != restore_sink.name:
                shutil.move(str(copied_active), str(restore_sink))

    records = 0
    if archive.get("segments"):
        records = sum(
            int(segment.get("record_count", 0)) for segment in archive["segments"]
        )

    restored_manifest = {
        "schema_version": "1",
        "segments": segments_meta,
        "head_hash": archive.get("head_hash"),
        "next_sequence": records + 1,
    }
    (restore_sink.parent / f"{restore_sink.name}.manifest.json").write_text(
        json.dumps(restored_manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return {
        "restored_audit_path": str(restore_sink),
        "records": records,
        "head": archive.get("head_hash"),
    }
