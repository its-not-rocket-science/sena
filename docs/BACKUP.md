# Backup and Restore Runbook

SENA supports timestamped backups for SQLite policy state and JSONL audit artifacts. For supported integrations, also snapshot the reliability SQLite file managed via `SENA_INTEGRATION_RELIABILITY_SQLITE_PATH`.

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

Also snapshot integration reliability state (same backup window):

```bash
cp /var/lib/sena/integration-reliability.db \
  /var/backups/sena/integration-reliability-$(date +%Y%m%dT%H%M%SZ).db
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

If restoring supported integration delivery state, restore the reliability snapshot explicitly:

```bash
cp /var/backups/sena/integration-reliability-20260403T000000Z.db \
  /var/lib/sena/integration-reliability.db
```

By default restore runs audit chain verification against the restored primary `.jsonl` file.

## Cron example

Run daily at 03:15 UTC:

```cron
15 3 * * * cd /opt/sena && /usr/bin/python scripts/backup.py --sqlite-db /var/lib/sena/policy_registry.db --audit-dir /var/lib/sena/audit --output-dir /var/backups/sena --s3-bucket sena-prod-backups --s3-prefix sena/prod --retention-days 30 && cp /var/lib/sena/integration-reliability.db /var/backups/sena/integration-reliability-$(date +\%Y\%m\%dT\%H\%M\%SZ).db >> /var/log/sena/backup.log 2>&1
```

## Post-restore supported-path checks

After restore, validate supported Jira/ServiceNow operator endpoints instead of direct DB inspection:

```bash
export SENA_BASE_URL="${SENA_BASE_URL:-http://127.0.0.1:8000}"
export SENA_ADMIN_API_KEY="${SENA_ADMIN_API_KEY:?set admin key}"
export CONNECTOR="${CONNECTOR:-jira}" # or servicenow

curl -fsS "$SENA_BASE_URL/v1/ready" -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
curl -fsS "$SENA_BASE_URL/v1/integrations/$CONNECTOR/admin/outbound/completions?limit=5" -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
curl -fsS "$SENA_BASE_URL/v1/integrations/$CONNECTOR/admin/outbound/dead-letter?limit=5" -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
curl -fsS "$SENA_BASE_URL/v1/integrations/$CONNECTOR/admin/outbound/duplicates/summary" -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
```

## Verification service (daily audit integrity)

Set:
- `SENA_AUDIT_VERIFY_DAILY_ENABLED=true`
- `SENA_AUDIT_VERIFY_REPORT_DIR=/var/log/sena`
- optional `SENA_AUDIT_VERIFY_ALERT_WEBHOOK=https://...`

Service writes `audit-verify-YYYY-MM-DD.json` reports and updates metric `sena_audit_verification_passed`.

## Automated restore drill helper

For a single-command backup->restore->verify drill, run:

```bash
python scripts/registry_backup_restore_drill.py \
  --sqlite-path /var/lib/sena/policy-registry.db \
  --audit-chain /var/lib/sena/audit/decisions.jsonl \
  --work-dir /tmp/sena-drill
```

Use `--dry-run` to print all underlying registry commands without changing files.
