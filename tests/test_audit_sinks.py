from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sena.audit.chain import append_audit_record, verify_audit_chain
from sena.audit.archive import create_audit_archive, restore_audit_archive, verify_audit_archive
from sena.audit.sinks import (
    AuditSinkError,
    JsonlFileAuditSink,
    RetentionPolicy,
    RotationPolicy,
    S3CompatibleAuditSink,
)


class FakeBody:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, object]] = {}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> None:
        del Bucket, ContentType
        self.objects[Key] = {"Body": Body, "LastModified": datetime.now(tz=timezone.utc)}

    def list_objects_v2(self, *, Bucket: str, Prefix: str) -> dict[str, object]:
        del Bucket
        contents = [
            {"Key": key, "LastModified": data["LastModified"]}
            for key, data in self.objects.items()
            if key.startswith(Prefix)
        ]
        return {"Contents": contents}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        del Bucket
        data = self.objects[Key]
        return {"Body": FakeBody(data["Body"])}

    def delete_objects(self, *, Bucket: str, Delete: dict[str, object]) -> None:
        del Bucket
        for item in Delete["Objects"]:
            key = item["Key"]
            self.objects.pop(key, None)


def test_jsonl_sink_rotation_and_verify(tmp_path) -> None:
    sink = JsonlFileAuditSink(
        path=str(tmp_path / "audit.jsonl"),
        append_only=True,
        rotation=RotationPolicy(max_file_bytes=300),
    )
    append_audit_record(sink, {"decision_id": "d1", "outcome": "APPROVED"})
    append_audit_record(sink, {"decision_id": "d2", "outcome": "BLOCKED"})
    append_audit_record(sink, {"decision_id": "d3", "outcome": "BLOCKED"})
    result = verify_audit_chain(sink)
    assert result["valid"] is True
    assert result["segments"]


def test_jsonl_sink_rejects_retention_in_append_only_mode(tmp_path) -> None:
    sink = JsonlFileAuditSink(
        path=str(tmp_path / "audit.jsonl"),
        append_only=True,
        retention=RetentionPolicy(max_records=1),
    )
    with pytest.raises(AuditSinkError):
        append_audit_record(sink, {"decision_id": "d1", "outcome": "APPROVED"})


def test_s3_compatible_sink_with_retention() -> None:
    fake = FakeS3Client()
    sink = S3CompatibleAuditSink(
        bucket="audit-bucket",
        key_prefix="tenant-a/audit",
        append_only=False,
        retention=RetentionPolicy(max_records=1, max_age_days=1),
        client=fake,
    )

    append_audit_record(sink, {"decision_id": "d1", "outcome": "APPROVED"})
    assert len(fake.objects) == 1

    key = next(iter(fake.objects.keys()))
    fake.objects[key]["LastModified"] = datetime.now(tz=timezone.utc) - timedelta(days=2)

    append_audit_record(sink, {"decision_id": "d2", "outcome": "BLOCKED"})
    assert len(fake.objects) == 1

    records = sink.load_records()
    assert records[0]["decision_id"] == "d2"
    assert json.loads(json.dumps(records[0]))["chain_hash"]


def test_jsonl_sink_concurrent_writers_preserve_chain(tmp_path) -> None:
    sink = JsonlFileAuditSink(path=str(tmp_path / "audit.jsonl"), rotation=RotationPolicy(max_file_bytes=1_000_000))

    def writer(i: int) -> None:
        append_audit_record(sink, {"decision_id": f"d{i}", "outcome": "APPROVED"})

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(25)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    result = verify_audit_chain(sink)
    assert result["valid"] is True
    assert result["records"] == 25


def test_manifest_missing_segment_reported(tmp_path) -> None:
    sink = JsonlFileAuditSink(path=str(tmp_path / "audit.jsonl"), rotation=RotationPolicy(max_file_bytes=250))
    for i in range(4):
        append_audit_record(sink, {"decision_id": f"d{i}", "outcome": "APPROVED"})

    manifest = tmp_path / "audit.jsonl.manifest.json"
    data = json.loads(manifest.read_text())
    first_segment = data["segments"][0]["file"]
    (tmp_path / first_segment).unlink()

    broken = verify_audit_chain(sink)
    assert broken["valid"] is False
    assert any("missing_segment" in err for err in broken["errors"])


def test_partial_write_line_is_detected(tmp_path) -> None:
    sink = JsonlFileAuditSink(path=str(tmp_path / "audit.jsonl"))
    append_audit_record(sink, {"decision_id": "d1", "outcome": "APPROVED"})
    with (tmp_path / "audit.jsonl").open("a", encoding="utf-8") as handle:
        handle.write('{"decision_id":"broken"')

    result = verify_audit_chain(sink)
    assert result["valid"] is False
    assert any("malformed_record" in err for err in result["errors"])


def test_manifest_next_sequence_mismatch_is_detected(tmp_path) -> None:
    sink = JsonlFileAuditSink(path=str(tmp_path / "audit.jsonl"), rotation=RotationPolicy(max_file_bytes=250))
    for i in range(3):
        append_audit_record(sink, {"decision_id": f"d{i}", "outcome": "APPROVED"})

    manifest = tmp_path / "audit.jsonl.manifest.json"
    payload = json.loads(manifest.read_text())
    payload["next_sequence"] = 99
    manifest.write_text(json.dumps(payload))

    broken = verify_audit_chain(sink)
    assert broken["valid"] is False
    assert any("manifest_next_sequence_mismatch" in err for err in broken["errors"])


def test_rotation_manifest_contains_archive_metadata(tmp_path) -> None:
    sink = JsonlFileAuditSink(path=str(tmp_path / "audit.jsonl"), rotation=RotationPolicy(max_file_bytes=250))
    for i in range(4):
        append_audit_record(sink, {"decision_id": f"d{i}", "outcome": "APPROVED"})

    manifest = json.loads((tmp_path / "audit.jsonl.manifest.json").read_text())
    assert manifest["segments"]
    first_segment = manifest["segments"][0]
    assert first_segment["archive"]["archive_status"] == "local_rotated"
    assert first_segment["archive"]["archive_class"] == "warm"


def test_archived_chain_verifies_across_rotated_segments(tmp_path) -> None:
    sink = JsonlFileAuditSink(path=str(tmp_path / "audit.jsonl"), rotation=RotationPolicy(max_file_bytes=250))
    for i in range(6):
        append_audit_record(sink, {"decision_id": f"d{i}", "outcome": "APPROVED"})

    archive_result = create_audit_archive(str(tmp_path / "audit.jsonl"), str(tmp_path / "archive"))
    verify_result = verify_audit_archive(archive_result["manifest_path"])
    assert verify_result["valid"] is True
    assert verify_result["segments"] >= 2


def test_archived_chain_detects_truncated_segment(tmp_path) -> None:
    sink = JsonlFileAuditSink(path=str(tmp_path / "audit.jsonl"), rotation=RotationPolicy(max_file_bytes=250))
    for i in range(5):
        append_audit_record(sink, {"decision_id": f"d{i}", "outcome": "APPROVED"})

    archive_result = create_audit_archive(str(tmp_path / "audit.jsonl"), str(tmp_path / "archive"))
    manifest = json.loads(Path(archive_result["manifest_path"]).read_text())
    first_segment = tmp_path / "archive" / manifest["segments"][0]["archived_file"]
    first_segment.write_text(first_segment.read_text()[:-20], encoding="utf-8")

    verify_result = verify_audit_archive(archive_result["manifest_path"])
    assert verify_result["valid"] is False
    assert any("archive_checksum_mismatch" in error for error in verify_result["errors"])


def test_archived_chain_detects_modified_historical_entry(tmp_path) -> None:
    sink = JsonlFileAuditSink(path=str(tmp_path / "audit.jsonl"), rotation=RotationPolicy(max_file_bytes=250))
    for i in range(5):
        append_audit_record(sink, {"decision_id": f"d{i}", "outcome": "APPROVED"})

    archive_result = create_audit_archive(str(tmp_path / "audit.jsonl"), str(tmp_path / "archive"))
    manifest = json.loads(Path(archive_result["manifest_path"]).read_text())
    first_segment_path = tmp_path / "archive" / manifest["segments"][0]["archived_file"]
    segment_lines = first_segment_path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(segment_lines[0])
    tampered["outcome"] = "BLOCKED"
    segment_lines[0] = json.dumps(tampered, sort_keys=True, separators=(",", ":"))
    first_segment_path.write_text("\n".join(segment_lines) + "\n", encoding="utf-8")

    verify_result = verify_audit_archive(archive_result["manifest_path"])
    assert verify_result["valid"] is False
    assert any("archive_checksum_mismatch" in error for error in verify_result["errors"])


def test_restore_archive_reverifies_cleanly(tmp_path) -> None:
    sink = JsonlFileAuditSink(path=str(tmp_path / "audit.jsonl"), rotation=RotationPolicy(max_file_bytes=250))
    for i in range(5):
        append_audit_record(sink, {"decision_id": f"d{i}", "outcome": "APPROVED"})

    archive_result = create_audit_archive(str(tmp_path / "audit.jsonl"), str(tmp_path / "archive"))
    restore_audit_archive(archive_result["manifest_path"], str(tmp_path / "restore" / "audit.jsonl"))

    restored_verify = verify_audit_chain(str(tmp_path / "restore" / "audit.jsonl"))
    assert restored_verify["valid"] is True


def test_archived_chain_detects_missing_segment(tmp_path) -> None:
    sink = JsonlFileAuditSink(path=str(tmp_path / "audit.jsonl"), rotation=RotationPolicy(max_file_bytes=250))
    for i in range(5):
        append_audit_record(sink, {"decision_id": f"d{i}", "outcome": "APPROVED"})

    archive_result = create_audit_archive(str(tmp_path / "audit.jsonl"), str(tmp_path / "archive"))
    manifest = json.loads(Path(archive_result["manifest_path"]).read_text())
    missing_segment = tmp_path / "archive" / manifest["segments"][0]["archived_file"]
    missing_segment.unlink()

    verify_result = verify_audit_archive(archive_result["manifest_path"])
    assert verify_result["valid"] is False
    assert any("missing_archive_segment" in error for error in verify_result["errors"])
