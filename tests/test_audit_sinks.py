from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from sena.audit.chain import append_audit_record, verify_audit_chain
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
        rotation=RotationPolicy(max_file_bytes=200),
    )
    append_audit_record(sink, {"decision_id": "d1", "outcome": "APPROVED"})
    append_audit_record(sink, {"decision_id": "d2", "outcome": "BLOCKED"})
    result = verify_audit_chain(sink)
    assert result["valid"] is True


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
