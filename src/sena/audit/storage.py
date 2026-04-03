from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sena.audit.chain import append_audit_record
from sena.audit.sinks import JsonlFileAuditSink


class AuditStorageError(RuntimeError):
    """Raised when an audit storage backend is misconfigured or unavailable."""


class AuditStorage(ABC):
    @abstractmethod
    def append(self, entry: dict[str, Any]) -> str: ...

    @abstractmethod
    def read(self, entry_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def verify_immutable(self) -> bool: ...


@dataclass
class LocalFileStorage(AuditStorage):
    path: str

    def append(self, entry: dict[str, Any]) -> str:
        payload = dict(entry)
        payload.setdefault("storage_entry_id", payload.get("decision_id") or f"loc-{uuid4().hex}")
        persisted = append_audit_record(JsonlFileAuditSink(path=self.path), payload)
        return str(persisted.get("storage_entry_id") or persisted.get("decision_id") or persisted.get("chain_hash"))

    def read(self, entry_id: str) -> dict[str, Any]:
        sink = JsonlFileAuditSink(path=self.path)
        for row in sink.load_records():
            keys = (
                str(row.get("storage_entry_id") or ""),
                str(row.get("decision_id") or ""),
                str(row.get("chain_hash") or ""),
            )
            if entry_id in keys:
                return row
        raise KeyError(f"audit entry not found: {entry_id}")

    def verify_immutable(self) -> bool:
        # Local JSONL development sink is append-focused but not WORM-enforced.
        return False


@dataclass
class S3ObjectLockStorage(AuditStorage):
    bucket: str
    prefix: str
    retention_days: int = 365
    client: Any | None = None

    def _client(self) -> Any:
        if self.client is not None:
            return self.client
        try:
            import boto3  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise AuditStorageError("boto3 is required for S3ObjectLockStorage") from exc
        return boto3.client("s3")

    def append(self, entry: dict[str, Any]) -> str:
        entry_id = str(entry.get("decision_id") or f"s3-{uuid4().hex}")
        key = f"{self.prefix.rstrip('/')}/{datetime.now(tz=timezone.utc).strftime('%Y/%m/%d')}/{entry_id}.json"
        body = json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        retain_until = datetime.now(tz=timezone.utc) + timedelta(days=self.retention_days)
        self._client().put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
            ObjectLockMode="COMPLIANCE",
            ObjectLockRetainUntilDate=retain_until,
        )
        return entry_id

    def read(self, entry_id: str) -> dict[str, Any]:
        prefix = f"{self.prefix.rstrip('/')}"
        response = self._client().list_objects_v2(Bucket=self.bucket, Prefix=prefix)
        for item in response.get("Contents", []):
            key = str(item.get("Key", ""))
            if key.endswith(f"/{entry_id}.json"):
                obj = self._client().get_object(Bucket=self.bucket, Key=key)
                return json.loads(obj["Body"].read().decode("utf-8"))
        raise KeyError(f"audit entry not found: {entry_id}")

    def verify_immutable(self) -> bool:
        cfg = self._client().get_object_lock_configuration(Bucket=self.bucket)
        lock_cfg = cfg.get("ObjectLockConfiguration", {})
        if lock_cfg.get("ObjectLockEnabled") != "Enabled":
            return False
        rule = lock_cfg.get("Rule", {}).get("DefaultRetention", {})
        return str(rule.get("Mode", "")).upper() == "COMPLIANCE"


@dataclass
class AzureImmutableBlobStorage(AuditStorage):
    account_url: str
    container: str
    prefix: str
    retention_days: int = 365
    client: Any | None = None

    def _client(self) -> Any:
        if self.client is not None:
            return self.client
        try:
            from azure.storage.blob import BlobServiceClient  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise AuditStorageError(
                "azure-storage-blob is required for AzureImmutableBlobStorage"
            ) from exc
        conn = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if not conn:
            raise AuditStorageError("AZURE_STORAGE_CONNECTION_STRING is required")
        return BlobServiceClient.from_connection_string(conn)

    def append(self, entry: dict[str, Any]) -> str:
        entry_id = str(entry.get("decision_id") or f"azure-{uuid4().hex}")
        blob_name = f"{self.prefix.rstrip('/')}/{datetime.now(tz=timezone.utc).strftime('%Y/%m/%d')}/{entry_id}.json"
        container = self._client().get_container_client(self.container)
        body = json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str)
        blob_client = container.get_blob_client(blob_name)
        blob_client.upload_blob(body, overwrite=False)
        if hasattr(blob_client, "set_immutability_policy"):
            expires = datetime.now(tz=timezone.utc) + timedelta(days=self.retention_days)
            blob_client.set_immutability_policy(expiry_time=expires)
        return entry_id

    def read(self, entry_id: str) -> dict[str, Any]:
        container = self._client().get_container_client(self.container)
        for blob in container.list_blobs(name_starts_with=self.prefix.rstrip("/")):
            name = str(blob.name)
            if name.endswith(f"/{entry_id}.json"):
                payload = container.download_blob(name).readall().decode("utf-8")
                return json.loads(payload)
        raise KeyError(f"audit entry not found: {entry_id}")

    def verify_immutable(self) -> bool:
        container = self._client().get_container_client(self.container)
        for blob in container.list_blobs(name_starts_with=self.prefix.rstrip("/")):
            policy = getattr(blob, "immutability_policy", None)
            if policy is not None:
                return True
        return False


def storage_from_env(audit_sink_jsonl: str | None) -> AuditStorage | None:
    backend = os.getenv("SENA_AUDIT_STORAGE_BACKEND", "local_file").strip().lower()
    if backend in {"", "none"}:
        return None
    if backend == "local_file":
        if not audit_sink_jsonl:
            raise AuditStorageError(
                "SENA_AUDIT_SINK_JSONL must be configured for local_file backend"
            )
        Path(audit_sink_jsonl).parent.mkdir(parents=True, exist_ok=True)
        return LocalFileStorage(path=audit_sink_jsonl)
    if backend == "s3_object_lock":
        bucket = os.getenv("SENA_AUDIT_S3_BUCKET")
        prefix = os.getenv("SENA_AUDIT_S3_PREFIX", "sena/audit")
        if not bucket:
            raise AuditStorageError("SENA_AUDIT_S3_BUCKET is required")
        days = int(os.getenv("SENA_AUDIT_WORM_RETENTION_DAYS", "365"))
        return S3ObjectLockStorage(bucket=bucket, prefix=prefix, retention_days=days)
    if backend == "azure_immutable_blob":
        account_url = os.getenv("SENA_AUDIT_AZURE_ACCOUNT_URL")
        container = os.getenv("SENA_AUDIT_AZURE_CONTAINER")
        prefix = os.getenv("SENA_AUDIT_AZURE_PREFIX", "sena/audit")
        if not account_url or not container:
            raise AuditStorageError(
                "SENA_AUDIT_AZURE_ACCOUNT_URL and SENA_AUDIT_AZURE_CONTAINER are required"
            )
        days = int(os.getenv("SENA_AUDIT_WORM_RETENTION_DAYS", "365"))
        return AzureImmutableBlobStorage(
            account_url=account_url,
            container=container,
            prefix=prefix,
            retention_days=days,
        )
    raise AuditStorageError(f"Unsupported SENA_AUDIT_STORAGE_BACKEND: {backend}")
