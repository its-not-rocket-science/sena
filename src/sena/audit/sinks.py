from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol


class AuditSinkError(RuntimeError):
    """Raised when sink operations fail or are misconfigured."""


class AuditSink(Protocol):
    """Pluggable storage contract for tamper-evident audit records."""

    def load_records(self) -> list[dict[str, Any]]:
        ...

    def append(self, payload: dict[str, Any]) -> None:
        ...


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

    def load_records(self) -> list[dict[str, Any]]:
        sink = Path(self.path)
        if not sink.parent.exists():
            return []

        candidates = sorted(
            sink.parent.glob(f"{sink.name}*"),
            key=lambda file: (file == sink, file.name),
        )
        records: list[dict[str, Any]] = []
        for candidate in candidates:
            if not candidate.is_file():
                continue
            with candidate.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        records.append(json.loads(line))
        return records

    def append(self, payload: dict[str, Any]) -> None:
        sink = Path(self.path)
        sink.parent.mkdir(parents=True, exist_ok=True)

        line = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str) + "\n"
        next_size = (sink.stat().st_size if sink.exists() else 0) + len(line.encode("utf-8"))
        if self.rotation and self.rotation.max_file_bytes and sink.exists():
            if next_size > self.rotation.max_file_bytes:
                self._rotate_file(sink)

        with sink.open("a", encoding="utf-8") as handle:
            handle.write(line)

        self._enforce_retention()

    def _rotate_file(self, sink: Path) -> None:
        timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
        rotated = sink.with_suffix(f"{sink.suffix}.{timestamp}.rotated")
        sink.rename(rotated)

    def _enforce_retention(self) -> None:
        if self.retention is None:
            return
        if self.append_only:
            raise AuditSinkError(
                "retention policy requires append_only=False because old records/files may be deleted"
            )

        sink = Path(self.path)
        if not sink.parent.exists():
            return

        candidates = sorted(sink.parent.glob(f"{sink.name}*"), key=lambda p: p.stat().st_mtime)
        now = datetime.now(tz=timezone.utc)

        if self.retention.max_age_days is not None:
            max_age = timedelta(days=self.retention.max_age_days)
            for file in list(candidates):
                modified = datetime.fromtimestamp(file.stat().st_mtime, tz=timezone.utc)
                if now - modified > max_age:
                    file.unlink(missing_ok=True)
                    candidates.remove(file)

        if self.retention.max_records is not None and len(candidates) > self.retention.max_records:
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
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        client.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType="application/json")
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

        if self.retention.max_records is not None and len(objects) > self.retention.max_records:
            excess = len(objects) - self.retention.max_records
            for item in objects[:excess]:
                to_delete.append({"Key": item["Key"]})

        if to_delete:
            unique = {item["Key"]: item for item in to_delete}
            client.delete_objects(Bucket=self.bucket, Delete={"Objects": list(unique.values())})
