from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _upload_s3(file_path: Path, bucket: str, key: str) -> str:
    try:
        import boto3  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("boto3 is required for S3 backup uploads") from exc
    client = boto3.client("s3")
    client.upload_file(str(file_path), bucket, key)
    return f"s3://{bucket}/{key}"


def _enforce_retention(bucket: str, prefix: str, retention_days: int) -> None:
    try:
        import boto3  # type: ignore
    except ImportError:
        return
    client = boto3.client("s3")
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=retention_days)
    resp = client.list_objects_v2(Bucket=bucket, Prefix=prefix)
    to_delete = []
    for item in resp.get("Contents", []):
        if item["LastModified"] < cutoff:
            to_delete.append({"Key": item["Key"]})
    if to_delete:
        client.delete_objects(Bucket=bucket, Delete={"Objects": to_delete})


def run_backup(sqlite_db: Path, audit_dir: Path, output_dir: Path, s3_bucket: str | None, s3_prefix: str, retention_days: int) -> dict:
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = output_dir / f"backup-{timestamp}"
    backup_root.mkdir(parents=True, exist_ok=True)

    db_backup = backup_root / sqlite_db.name
    shutil.copy2(sqlite_db, db_backup)

    audit_backup_dir = backup_root / "audit"
    audit_backup_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for src in sorted(audit_dir.glob("*.jsonl*")):
        dst = audit_backup_dir / src.name
        shutil.copy2(src, dst)
        copied.append(str(dst))

    manifest = {
        "timestamp": timestamp,
        "sqlite_db": str(db_backup),
        "audit_files": copied,
        "s3_objects": [],
    }

    if s3_bucket:
        for file_path in [db_backup, *[Path(p) for p in copied]]:
            key = f"{s3_prefix.rstrip('/')}/{timestamp}/{file_path.name}"
            uri = _upload_s3(file_path, s3_bucket, key)
            manifest["s3_objects"].append(uri)
        _enforce_retention(s3_bucket, s3_prefix.rstrip("/"), retention_days)

    manifest_path = backup_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    manifest["manifest"] = str(manifest_path)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Create SENA SQLite + audit backup manifest")
    parser.add_argument("--sqlite-db", required=True, type=Path)
    parser.add_argument("--audit-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--s3-bucket")
    parser.add_argument("--s3-prefix", default="sena/backups")
    parser.add_argument("--retention-days", type=int, default=30)
    args = parser.parse_args()

    manifest = run_backup(
        sqlite_db=args.sqlite_db,
        audit_dir=args.audit_dir,
        output_dir=args.output_dir,
        s3_bucket=args.s3_bucket,
        s3_prefix=args.s3_prefix,
        retention_days=args.retention_days,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
