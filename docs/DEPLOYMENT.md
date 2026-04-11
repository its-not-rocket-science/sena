# SENA Production Deployment Guide

## Quick start matrix
- **Kubernetes (Helm):** use `examples/k8s_admission_demo` as base values and wire secrets via your vault.
- **Terraform:** create a module that provisions container runtime + managed PostgreSQL + secrets backend.
- **Docker Compose (production variant):** run API, Postgres, Prometheus, and backup sidecar with auth enabled.

## Environment variables
- `SENA_RUNTIME_MODE=production`
- `SENA_API_KEY_ENABLED=true`
- `SENA_API_KEYS=<comma-separated keys>`
- `SENA_POLICY_DIR=<mounted policy bundle>`
- `SENA_BUNDLE_NAME`, `SENA_BUNDLE_VERSION`
- `SENA_AUDIT_SINK_JSONL=<persistent volume path>`
- `SENA_INTEGRATION_RELIABILITY_SQLITE_PATH=<persistent volume path>`
- `SENA_JIRA_MAPPING_CONFIG`, `SENA_JIRA_WEBHOOK_SECRET` (when Jira enabled)
- `SENA_SERVICENOW_MAPPING_CONFIG`, `SENA_SERVICENOW_WEBHOOK_SECRET` (when ServiceNow enabled)
- `SENA_RATE_LIMIT_REQUESTS`, `SENA_RATE_LIMIT_WINDOW_SECONDS`
- `SENA_REQUEST_TIMEOUT_SECONDS`, `SENA_REQUEST_MAX_BYTES`

### Connector reliability requirement (Jira / ServiceNow)
- In production mode (`SENA_RUNTIME_MODE=production`), enabling Jira or ServiceNow mappings requires `SENA_INTEGRATION_RELIABILITY_SQLITE_PATH`.
- Production startup fails fast if this path is missing or if `SENA_INTEGRATION_RELIABILITY_ALLOW_INMEMORY=true`.
- In development/pilot, connector reliability defaults to durable SQLite; set `SENA_INTEGRATION_RELIABILITY_ALLOW_INMEMORY=true` only for demos/tests.

## Kubernetes Helm chart pattern (examples)
Use the `examples/k8s_admission_demo` assets as a reference and expose `/v1/health` and `/v1/ready` probes.

## Terraform module guidance (AWS/GCP/Azure)
Provision:
1. Container platform (EKS/GKE/AKS or ECS/Cloud Run/App Service).
2. Managed PostgreSQL.
3. Secret store (Secrets Manager/Secret Manager/Key Vault).
4. Observability stack (Prometheus-compatible scrape + logs).

## Docker Compose production variant
Recommended services:
- `sena-api` (read-only rootfs, auth enabled)
- `postgres` (primary data store)
- `prometheus` + `grafana`
- `backup` cron sidecar (`pg_dump` + audit artifact snapshots)

## Scaling guidance
SQLite is acceptable for local/dev and single-instance pilots. For production horizontal scaling, migrate policy and idempotency state to PostgreSQL and run multiple API replicas behind a load balancer.

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
