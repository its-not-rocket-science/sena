# SENA Deployment Guide (Supported Product Path)

> **Scope:** This guide is for the supported product only: deterministic Jira + ServiceNow approval decisioning with replayable audit evidence.
> For Kubernetes admission-controller demo assets, see `docs/EXPERIMENTAL_INDEX.md`.

## Quick start matrix
- **Single-instance API (recommended for alpha/pilot):** run API + persistent SQLite volumes for policy, audit, and reliability data.
- **Container-orchestrated runtime:** deploy the same supported API container behind your platform ingress/load balancer.
- **Monitoring stack (optional):** `docker-compose-monitoring.yml` + `monitoring/` for metrics visualization.

## Environment variables
- `SENA_RUNTIME_MODE=production`
- `SENA_API_KEY_ENABLED=true`
- `SENA_API_KEYS=<comma-separated keys>`
- `SENA_POLICY_DIR=<mounted policy bundle>`
- `SENA_BUNDLE_NAME`, `SENA_BUNDLE_VERSION`
- `SENA_AUDIT_SINK_JSONL=<persistent volume path>`
- `SENA_INGESTION_QUEUE_BACKEND=<sqlite|redis>` (`memory` is development-only)
- `SENA_PROCESSING_SQLITE_PATH=<persistent volume path>` (required when `SENA_INGESTION_QUEUE_BACKEND=sqlite`)
- `SENA_INGESTION_QUEUE_REDIS_URL=<redis url>` (required when `SENA_INGESTION_QUEUE_BACKEND=redis`)
- `SENA_INTEGRATION_RELIABILITY_SQLITE_PATH=<persistent volume path>`
- `SENA_JIRA_MAPPING_CONFIG`, `SENA_JIRA_WEBHOOK_SECRET` (when Jira enabled)
- `SENA_SERVICENOW_MAPPING_CONFIG`, `SENA_SERVICENOW_WEBHOOK_SECRET` (when ServiceNow enabled)
- `SENA_RATE_LIMIT_REQUESTS`, `SENA_RATE_LIMIT_WINDOW_SECONDS`
- `SENA_REQUEST_TIMEOUT_SECONDS`, `SENA_REQUEST_MAX_BYTES`

### Connector reliability requirement (Jira / ServiceNow)
- In production mode (`SENA_RUNTIME_MODE=production`), enabling Jira or ServiceNow mappings requires `SENA_INTEGRATION_RELIABILITY_SQLITE_PATH`.
- Production startup fails fast if this path is missing or if `SENA_INTEGRATION_RELIABILITY_ALLOW_INMEMORY=true`.
- In development/pilot, connector reliability defaults to durable SQLite; set `SENA_INTEGRATION_RELIABILITY_ALLOW_INMEMORY=true` only for demos/tests.

### Ingestion queue durability requirement
- In `pilot` and `production`, `SENA_INGESTION_QUEUE_BACKEND=memory` is rejected at startup.
- Use `sqlite` for single-node pilot durability or `redis` for networked queue deployments.
- Startup fails clearly when durable queue configuration is missing or invalid (for example: redis without `SENA_INGESTION_QUEUE_REDIS_URL`, or sqlite with a missing parent directory for `SENA_PROCESSING_SQLITE_PATH`).

## Backup / restore runbook
1. Back up policy registry (`scripts/backup_policy_registry.py`).
2. Archive audit sink artifacts (`scripts/backup.py`).
3. Back up integration reliability DB at `SENA_INTEGRATION_RELIABILITY_SQLITE_PATH`.
4. Verify backups with checksum + restore drill in staging.
5. Restore with `scripts/restore_policy_registry.py` and `scripts/restore.py`.

## Operator startup and supported-path smoke checks

Use this exact sequence after deployment:

```bash
export SENA_BASE_URL="https://sena.example.com"
export SENA_ADMIN_API_KEY="${SENA_ADMIN_API_KEY:?set admin key}"
export CONNECTOR="${CONNECTOR:-jira}" # or servicenow

sena production-check --format both
curl -fsS "$SENA_BASE_URL/v1/health" -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
curl -fsS "$SENA_BASE_URL/v1/ready" -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
curl -fsS "$SENA_BASE_URL/v1/integrations/$CONNECTOR/admin/outbound/completions?limit=5" -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
curl -fsS "$SENA_BASE_URL/v1/integrations/$CONNECTOR/admin/outbound/dead-letter?limit=5" -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
curl -fsS "$SENA_BASE_URL/v1/integrations/$CONNECTOR/admin/outbound/duplicates/summary" -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
```

If these succeed, operators can handle supported Jira/ServiceNow incidents through admin endpoints without direct SQLite inspection.
