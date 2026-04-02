from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol


class AuditSinkError(RuntimeError):
    """Raised when sink operations fail or are misconfigured."""


class AuditSink(Protocol):
    """Pluggable storage contract for tamper-evident audit records."""

    def load_records(self) -> list[dict[str, Any]]: ...

    def append(self, payload: dict[str, Any]) -> None: ...


@dataclass(frozen=True)
class RetentionPolicy:
    max_records: int | None = None
    max_age_days: int | None = None


@dataclass(frozen=True)
class RotationPolicy:
    max_file_bytes: int | None = None


@dataclass
class JsonlFileAuditSink:
    path: str
    append_only: bool = True
    retention: RetentionPolicy | None = None
    rotation: RotationPolicy | None = None

    def _sink_path(self) -> Path:
        return Path(self.path)

    def _lock_path(self) -> Path:
        sink = self._sink_path()
        return sink.with_name(f"{sink.name}.lock")

    def _manifest_path(self) -> Path:
        sink = self._sink_path()
        return sink.with_name(f"{sink.name}.manifest.json")

    def _acquire_lock(self):
        import fcntl

        lock = self._lock_path()
        lock.parent.mkdir(parents=True, exist_ok=True)
        handle = lock.open("a+", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return handle

    def _read_manifest(self) -> dict[str, Any]:
        path = self._manifest_path()
        manifest_present = path.exists()
        if not path.exists():
            return {
                "schema_version": "1",
                "segments": [],
                "head_hash": None,
                "next_sequence": 1,
                "manifest_present": False,
            }
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AuditSinkError(f"Malformed audit manifest: {path}") from exc
        if not isinstance(payload, dict):
            raise AuditSinkError(f"Malformed audit manifest root object: {path}")
        payload.setdefault("schema_version", "1")
        payload.setdefault("segments", [])
        payload.setdefault("head_hash", None)
        payload.setdefault("next_sequence", 1)
        payload["manifest_present"] = manifest_present
        return payload

    def _write_manifest(self, payload: dict[str, Any]) -> None:
        path = self._manifest_path()
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _segment_name(self, seq: int) -> str:
        sink = self._sink_path()
        return f"{sink.name}.seg-{seq:06d}.jsonl"

    def _read_lines(self, file: Path) -> tuple[list[dict[str, Any]], list[str]]:
        records: list[dict[str, Any]] = []
        malformed: list[str] = []
        with file.open("r", encoding="utf-8") as handle:
            for idx, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    malformed.append(f"{file.name}:{idx}")
                    continue
                if not isinstance(payload, dict):
                    malformed.append(f"{file.name}:{idx}")
                    continue
                records.append(payload)
        return records, malformed

    def _segment_record_count(self, file: Path) -> int:
        count = 0
        with file.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    count += 1
        return count

    def load_records_detailed(self) -> dict[str, Any]:
        sink = self._sink_path()
        if not sink.parent.exists():
            return {"records": [], "issues": [], "segments": []}

        manifest = self._read_manifest()
        issues: list[str] = []
        segments_meta: list[dict[str, Any]] = []
        records: list[dict[str, Any]] = []

        manifest_segments = manifest.get("segments", [])
        previous_last_sequence = None
        for segment_index, segment in enumerate(manifest_segments, start=1):
            file = sink.parent / segment["file"]
            if not file.exists():
                issues.append(f"missing_segment:{segment['file']}")
                continue
            segment_records, malformed = self._read_lines(file)
            if malformed:
                issues.extend([f"malformed_record:{item}" for item in malformed])
            expected_count = segment.get("record_count")
            if isinstance(expected_count, int) and expected_count != len(
                segment_records
            ):
                issues.append(
                    f"segment_record_count_mismatch:{segment['file']}:expected={expected_count}:actual={len(segment_records)}"
                )
            first_seq = (
                segment_records[0].get("storage_sequence_number")
                if segment_records
                else None
            )
            last_seq = (
                segment_records[-1].get("storage_sequence_number")
                if segment_records
                else None
            )
            if segment.get("first_sequence") != first_seq:
                issues.append(
                    f"segment_first_sequence_mismatch:{segment['file']}:expected={segment.get('first_sequence')}:actual={first_seq}"
                )
            if segment.get("last_sequence") != last_seq:
                issues.append(
                    f"segment_last_sequence_mismatch:{segment['file']}:expected={segment.get('last_sequence')}:actual={last_seq}"
                )
            if (
                segment_index > 1
                and previous_last_sequence is not None
                and first_seq is not None
            ):
                if first_seq != previous_last_sequence + 1:
                    issues.append(
                        f"segment_sequence_gap:{segment['file']}:previous_last={previous_last_sequence}:first={first_seq}"
                    )
            if isinstance(last_seq, int):
                previous_last_sequence = last_seq
            records.extend(segment_records)
            segments_meta.append(
                {
                    "file": segment["file"],
                    "records": len(segment_records),
                    "rotated": True,
                }
            )

        active_count = 0
        if sink.exists():
            active_records, malformed = self._read_lines(sink)
            if malformed:
                issues.extend([f"malformed_record:{item}" for item in malformed])
            records.extend(active_records)
            active_count = len(active_records)
            segments_meta.append(
                {"file": sink.name, "records": active_count, "rotated": False}
            )

        expected_next = manifest.get("next_sequence")
        if manifest.get("manifest_present", False) and isinstance(expected_next, int):
            total_from_manifest = 0
            for segment in manifest_segments:
                file = sink.parent / segment["file"]
                if file.exists():
                    total_from_manifest += self._segment_record_count(file)
            total_from_manifest += active_count
            actual_next = total_from_manifest + 1
            if expected_next != actual_next:
                issues.append(
                    f"manifest_next_sequence_mismatch:expected={expected_next}:actual={actual_next}"
                )

        return {
            "records": records,
            "issues": issues,
            "segments": segments_meta,
            "manifest": manifest,
        }

    def load_records(self) -> list[dict[str, Any]]:
        return self.load_records_detailed()["records"]

    def append(self, payload: dict[str, Any]) -> None:
        sink = self._sink_path()
        sink.parent.mkdir(parents=True, exist_ok=True)
        lock_handle = self._acquire_lock()
        try:
            encoded = (
                json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
                + "\n"
            ).encode("utf-8")
            if self.rotation and self.rotation.max_file_bytes and sink.exists():
                next_size = sink.stat().st_size + len(encoded)
                if next_size > self.rotation.max_file_bytes:
                    self._rotate_file(sink)

            fd = os.open(str(sink), os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
            try:
                os.write(fd, encoded)
                os.fsync(fd)
            finally:
                os.close(fd)

            self._enforce_retention()
        finally:
            lock_handle.close()

    def append_chained(self, payload: dict[str, Any], compute_hash) -> dict[str, Any]:
        sink = self._sink_path()
        sink.parent.mkdir(parents=True, exist_ok=True)
        lock_handle = self._acquire_lock()
        try:
            manifest = self._read_manifest()
            previous_chain_hash = manifest.get("head_hash")
            seq = int(manifest.get("next_sequence", 1))
            line_payload = dict(payload)
            line_payload["storage_sequence_number"] = seq
            line_payload["write_timestamp"] = datetime.now(tz=timezone.utc).isoformat()
            line_payload["previous_chain_hash"] = previous_chain_hash
            record_for_hash = {
                k: v for k, v in line_payload.items() if k not in {"chain_hash"}
            }
            line_payload["chain_hash"] = compute_hash(
                record_for_hash, previous_chain_hash
            )

            encoded = (
                json.dumps(
                    line_payload, sort_keys=True, separators=(",", ":"), default=str
                )
                + "\n"
            ).encode("utf-8")
            if self.rotation and self.rotation.max_file_bytes and sink.exists():
                next_size = sink.stat().st_size + len(encoded)
                if next_size > self.rotation.max_file_bytes:
                    self._rotate_file(sink)
                    manifest = self._read_manifest()

            fd = os.open(str(sink), os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
            try:
                os.write(fd, encoded)
                os.fsync(fd)
            finally:
                os.close(fd)

            manifest["head_hash"] = line_payload["chain_hash"]
            manifest["next_sequence"] = seq + 1
            self._write_manifest(manifest)
            self._enforce_retention()
            return line_payload
        finally:
            lock_handle.close()

    def _rotate_file(self, sink: Path) -> None:
        manifest = self._read_manifest()
        seq = len(manifest.get("segments", [])) + 1
        rotated = sink.with_name(self._segment_name(seq))
        os.replace(sink, rotated)
        records, malformed = self._read_lines(rotated)
        archive_metadata = {
            "archive_status": "local_rotated",
            "archive_class": "warm",
            "archive_uri": f"file://{rotated.resolve()}",
        }
        entry = {
            "file": rotated.name,
            "rotated_at": datetime.now(tz=timezone.utc).isoformat(),
            "record_count": len(records),
            "first_sequence": records[0].get("storage_sequence_number")
            if records
            else None,
            "last_sequence": records[-1].get("storage_sequence_number")
            if records
            else None,
            "first_chain_hash": records[0].get("chain_hash") if records else None,
            "last_chain_hash": records[-1].get("chain_hash") if records else None,
            "malformed_records": malformed,
            "archive": archive_metadata,
        }
        manifest.setdefault("segments", []).append(entry)
        self._write_manifest(manifest)

    def _enforce_retention(self) -> None:
        if self.retention is None:
            return
        if self.append_only:
            raise AuditSinkError(
                "retention policy requires append_only=False because old records/files may be deleted"
            )

        sink = self._sink_path()
        if not sink.parent.exists():
            return

        candidates = sorted(
            sink.parent.glob(f"{sink.name}*"), key=lambda p: p.stat().st_mtime
        )
        now = datetime.now(tz=timezone.utc)

        if self.retention.max_age_days is not None:
            max_age = timedelta(days=self.retention.max_age_days)
            for file in list(candidates):
                modified = datetime.fromtimestamp(file.stat().st_mtime, tz=timezone.utc)
                if now - modified > max_age:
                    file.unlink(missing_ok=True)
                    candidates.remove(file)

        if (
            self.retention.max_records is not None
            and len(candidates) > self.retention.max_records
        ):
            excess = len(candidates) - self.retention.max_records
            for file in candidates[:excess]:
                file.unlink(missing_ok=True)


@dataclass
class S3CompatibleAuditSink:
    bucket: str
    key_prefix: str
    append_only: bool = True
    retention: RetentionPolicy | None = None
    client: Any | None = None

    def _client(self) -> Any:
        if self.client is not None:
            return self.client
        try:
            import boto3  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise AuditSinkError(
                "S3CompatibleAuditSink requires boto3. Install boto3 to use S3-compatible audit storage."
            ) from exc
        return boto3.client("s3")

    def load_records(self) -> list[dict[str, Any]]:
        client = self._client()
        resp = client.list_objects_v2(Bucket=self.bucket, Prefix=self.key_prefix)
        contents = sorted(resp.get("Contents", []), key=lambda item: item["Key"])
        records: list[dict[str, Any]] = []
        for item in contents:
            obj = client.get_object(Bucket=self.bucket, Key=item["Key"])
            body = obj["Body"].read().decode("utf-8")
            records.append(json.loads(body))
        return records

    def append(self, payload: dict[str, Any]) -> None:
        client = self._client()
        now = datetime.now(tz=timezone.utc)
        key = f"{self.key_prefix.rstrip('/')}/{now.strftime('%Y/%m/%d/%H%M%S.%f')}.json"
        body = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        client.put_object(
            Bucket=self.bucket, Key=key, Body=body, ContentType="application/json"
        )
        self._enforce_retention(client)

    def _enforce_retention(self, client: Any) -> None:
        if self.retention is None:
            return
        if self.append_only:
            raise AuditSinkError(
                "retention policy requires append_only=False because S3 objects may be deleted"
            )

        response = client.list_objects_v2(Bucket=self.bucket, Prefix=self.key_prefix)
        objects = sorted(response.get("Contents", []), key=lambda item: item["Key"])
        now = datetime.now(tz=timezone.utc)
        to_delete: list[dict[str, str]] = []

        if self.retention.max_age_days is not None:
            max_age = timedelta(days=self.retention.max_age_days)
            for item in objects:
                if now - item["LastModified"] > max_age:
                    to_delete.append({"Key": item["Key"]})

        if (
            self.retention.max_records is not None
            and len(objects) > self.retention.max_records
        ):
            excess = len(objects) - self.retention.max_records
            for item in objects[:excess]:
                to_delete.append({"Key": item["Key"]})

        if to_delete:
            unique = {item["Key"]: item for item in to_delete}
            client.delete_objects(
                Bucket=self.bucket, Delete={"Objects": list(unique.values())}
            )
