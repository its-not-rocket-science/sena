# Backup and Restore Runbook

SENA supports timestamped backups for SQLite policy state and JSONL audit artifacts.

## Backup

```bash
python scripts/backup.py \
  --sqlite-db /var/lib/sena/policy_registry.db \
  --audit-dir /var/lib/sena/audit \
  --output-dir /var/backups/sena \
  --s3-bucket sena-prod-backups \
  --s3-prefix sena/prod \
  --retention-days 30
```

Output is a manifest JSON with:
- backup timestamp,
- local backup file paths,
- uploaded object URIs (when S3 configured),
- manifest path.

## Restore

```bash
python scripts/restore.py \
  --manifest /var/backups/sena/backup-20260403T000000Z/manifest.json \
  --restore-db /var/lib/sena/policy_registry.db \
  --restore-audit-dir /var/lib/sena/audit
```

By default restore runs audit chain verification against the restored primary `.jsonl` file.

## Cron example

Run daily at 03:15 UTC:

```cron
15 3 * * * cd /opt/sena && /usr/bin/python scripts/backup.py --sqlite-db /var/lib/sena/policy_registry.db --audit-dir /var/lib/sena/audit --output-dir /var/backups/sena --s3-bucket sena-prod-backups --s3-prefix sena/prod --retention-days 30 >> /var/log/sena/backup.log 2>&1
```

## Verification service (daily audit integrity)

Set:
- `SENA_AUDIT_VERIFY_DAILY_ENABLED=true`
- `SENA_AUDIT_VERIFY_REPORT_DIR=/var/log/sena`
- optional `SENA_AUDIT_VERIFY_ALERT_WEBHOOK=https://...`

Service writes `audit-verify-YYYY-MM-DD.json` reports and updates metric `sena_audit_verification_passed`.
