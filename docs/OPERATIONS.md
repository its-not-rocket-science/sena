# SENA Operations Guide

Application versioning: package and FastAPI app version are sourced from `sena.__version__` in `src/sena/__init__.py`.

## 1) Operating principles

- **Fail closed on startup**: SENA validates deployment-critical settings and aborts startup when unsafe or ambiguous.
- **Deterministic mode contracts**: `SENA_RUNTIME_MODE` governs stricter controls (`development`, `pilot`, `production`).
- **Explicit integrations**: each integration requires complete config; partial config is rejected.
- **Auditability first**: production mode requires a configured audit sink and strict release-signature enforcement.

## 2) Runtime modes

| Mode | Intent | Key behavior |
|---|---|---|
| `development` | local dev and tests | permissive defaults, optional auth and integrations |
| `pilot` | enterprise pilot pre-prod | same code-path as prod candidates, recommended strict auth/signing/audit |
| `production` | hardened runtime | mandatory auth, audit sink, strict signature verification + keyring, and fail-closed Jira/ServiceNow integration guardrails (mapping + webhook secret + durable reliability store) |

## 3) Startup validation (fail-fast)

SENA startup now fails for the following classes of misconfiguration:

- invalid `SENA_RUNTIME_MODE`
- invalid `SENA_POLICY_STORE_BACKEND`
- filesystem backend with missing/non-directory `SENA_POLICY_DIR`
- sqlite backend without `SENA_POLICY_STORE_SQLITE_PATH`
- sqlite backend with non-existent parent directory for sqlite file
- ambiguous API auth setup (e.g., key present but auth disabled, or both `SENA_API_KEY` and `SENA_API_KEYS` set)
- invalid API key role values
- partially configured Slack integration (`SENA_SLACK_BOT_TOKEN` without `SENA_SLACK_CHANNEL`, or inverse)
- missing mapping config files for webhook/Jira/ServiceNow when env vars are set
- production mode missing required controls:
  - `SENA_API_KEY_ENABLED=true` + keys
  - `SENA_AUDIT_SINK_JSONL`
  - `SENA_BUNDLE_SIGNATURE_STRICT=true`
  - `SENA_BUNDLE_SIGNATURE_KEYRING_DIR` existing directory
  - `SENA_JIRA_MAPPING_CONFIG` + `SENA_JIRA_WEBHOOK_SECRET` (or previous secret) when Jira integration is enabled
  - `SENA_SERVICENOW_MAPPING_CONFIG` + `SENA_SERVICENOW_WEBHOOK_SECRET` (or previous secret) when ServiceNow integration is enabled
  - `SENA_INTEGRATION_RELIABILITY_SQLITE_PATH` when Jira or ServiceNow integration is enabled

### Mandatory pre-deploy gate

Run this before every deployment:

```bash
sena production-check --format both
```

`sena production-check` must pass (exit code `0`) before promotion. It validates startup-fatal configuration and operational readiness contracts (auth, policy backend, audit sink, signature verification, integration mapping schema, request safety bounds, writable/restore prerequisites, and environment coherence).

## 4) Environment configuration reference

### Core runtime

- `SENA_RUNTIME_MODE`: `development` | `pilot` | `production`
- `SENA_API_HOST`, `SENA_API_PORT`: bind address/port
- `SENA_LOG_LEVEL`: Python logging level

### Policy source

- `SENA_POLICY_STORE_BACKEND`: `filesystem` (default) or `sqlite`
- `SENA_POLICY_DIR`: required directory when backend is `filesystem`
- `SENA_POLICY_STORE_SQLITE_PATH`: required when backend is `sqlite`
- `SENA_BUNDLE_NAME`, `SENA_BUNDLE_VERSION`: selection defaults

### API authentication and RBAC

- `SENA_API_KEY_ENABLED`: enable API key auth
- `SENA_API_KEY`: single admin key mode
- `SENA_API_KEYS`: `key:role,key2:role2` mode
  - roles: `admin`, `policy_author`, `reviewer`, `deployer`, `auditor`, `verifier`
- `SENA_JWT_AUTH_ENABLED`: enable JWT bearer-token auth
- `SENA_JWT_HS256_SECRET`: shared secret for local/dev HS256 verification
- `SENA_JWT_ISSUER`, `SENA_JWT_AUDIENCE`: optional claim constraints
- `SENA_JWT_REQUIRED_CLAIMS`: required token claims (CSV, default `sub`)
- `SENA_JWT_ROLE_CLAIM`: claim containing external role(s)
- `SENA_JWT_ROLE_MAPPING`: external-to-internal mapping (`idp-role:reviewer,...`)
- `SENA_ENFORCE_POLICY_ACTOR_IDENTITY`: optionally bind policy payload `actor_id` to JWT `sub` on evaluation endpoints
  - enforced ABAC attributes: `environment`, `bundle_name`, `action_type`

### Request safety controls

- `SENA_RATE_LIMIT_REQUESTS`
- `SENA_RATE_LIMIT_WINDOW_SECONDS`
- `SENA_REQUEST_MAX_BYTES`
- `SENA_REQUEST_TIMEOUT_SECONDS`

### Release signing and integrity

- `SENA_BUNDLE_RELEASE_MANIFEST_FILENAME` (default: `release-manifest.json`)
- `SENA_BUNDLE_SIGNATURE_STRICT`: require manifest verification
- `SENA_BUNDLE_SIGNATURE_KEYRING_DIR`: keyring directory for verification

### Promotion gates (candidate → active)

- `SENA_PROMOTION_GATE_REQUIRE_VALIDATION_ARTIFACT` (default: `true`)
- `SENA_PROMOTION_GATE_REQUIRE_SIMULATION` (default: `true`)
- `SENA_PROMOTION_GATE_REQUIRED_SCENARIO_IDS` (CSV list of scenario IDs that must be present in simulation evidence)
- `SENA_PROMOTION_GATE_MAX_CHANGED_OUTCOMES` (integer budget; promotion fails when exceeded)
- `SENA_PROMOTION_GATE_MAX_REGRESSIONS_BY_OUTCOME_TYPE` (JSON object, e.g. `{"BLOCKED->APPROVED":0}`)
- `SENA_PROMOTION_GATE_BREAK_GLASS_ENABLED` (default: `true`)

Break-glass promotions must set `break_glass=true` **and** provide `break_glass_reason`; otherwise promotion is rejected.

### Audit sink

- `SENA_AUDIT_SINK_JSONL`: file path to append audit records
- `SENA_AUDIT_VERIFY_ON_STARTUP_STRICT`: when `true`, startup runs full chain verification across rotated segments and fails closed on corruption/mismatch

### Integrations

- `SENA_WEBHOOK_MAPPING_CONFIG`
- `SENA_JIRA_MAPPING_CONFIG`
- `SENA_JIRA_WEBHOOK_SECRET`
- `SENA_JIRA_WEBHOOK_SECRET_PREVIOUS`
- `SENA_SERVICENOW_MAPPING_CONFIG`
- `SENA_SERVICENOW_WEBHOOK_SECRET`
- `SENA_SERVICENOW_WEBHOOK_SECRET_PREVIOUS`
- `SENA_INTEGRATION_RELIABILITY_SQLITE_PATH`
- `SENA_SLACK_BOT_TOKEN`
- `SENA_SLACK_CHANNEL`

## 5) Health and readiness semantics

- `GET /v1/health`: liveness + loaded bundle metadata (`status=ok`)
- `GET /v1/ready`: startup-contract readiness (`status=ready`) with checks:
  - `policy_bundle_loaded`
  - `auth_config_valid`
  - `policy_store_reachable`
  - `production_guardrails_enforced` (production mode only)

Because SENA fails startup on invalid critical settings, readiness reflects a **post-validation healthy process** rather than a best-effort degraded state.

## 6) Secure integration and secret handling guidance

- Keep all secrets out of repo and image layers.
- Inject secrets at runtime via env-injection mechanisms (Kubernetes Secrets, Vault agent templates, ECS task secrets, etc.).
- Rotate API keys and webhook shared secrets regularly.
- Use distinct secrets per environment (`dev`, `pilot`, `prod`).
- Ensure file permissions on audit sinks and keyring directories are restricted to the service account.

## 7) Operational examples

See `docs/DEPLOYMENT_PROFILES.md` for full deployment profiles and copy-paste examples for:

- local development
- containerized runtime
- enterprise pilot
- stricter production-like mode

## 7.1) Supported integration operator runbooks (Jira + ServiceNow)

Use this checklist for the supported integration paths only:
- `POST /v1/integrations/jira/webhook`
- `POST /v1/integrations/servicenow/webhook`

### Bring-up checklist

1. Set connector mapping + secret env vars:
   - Jira: `SENA_JIRA_MAPPING_CONFIG`, `SENA_JIRA_WEBHOOK_SECRET`
   - ServiceNow: `SENA_SERVICENOW_MAPPING_CONFIG`, `SENA_SERVICENOW_WEBHOOK_SECRET`
2. Set `SENA_INTEGRATION_RELIABILITY_SQLITE_PATH` to durable storage.
3. Run `sena production-check --format both` and confirm pass.
4. Verify readiness at `GET /v1/ready` and a known-good webhook fixture in non-production.

Copy-paste startup verification:

```bash
export SENA_BASE_URL="${SENA_BASE_URL:-http://127.0.0.1:8000}"
export SENA_ADMIN_API_KEY="${SENA_ADMIN_API_KEY:?set admin key}"

curl -fsS "$SENA_BASE_URL/v1/ready" \
  -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
```

### Live incident triage checklist

1. Confirm request authenticity failures via `error.code`:
   - `jira_authentication_failed`
   - `servicenow_authentication_failed`
2. Check mapping issues via `error.code`:
   - `jira_invalid_mapping` / `jira_missing_required_fields`
   - `servicenow_invalid_mapping` / `servicenow_missing_required_fields`
3. Inspect outbound reliability state:
   - `GET /v1/integrations/{connector}/admin/outbound/completions`
   - `GET /v1/integrations/{connector}/admin/outbound/dead-letter`
   - `GET /v1/integrations/{connector}/admin/outbound/duplicates/summary`
4. Replay only explicit dead-letter IDs after root-cause fix:
   - `POST /v1/integrations/{connector}/admin/outbound/dead-letter/replay`

### Recovery decision rules

- Prefer replay over manual redrive whenever the connector can safely retry.
- Use manual redrive only with an operator note:
  - `POST /v1/integrations/{connector}/admin/outbound/dead-letter/manual-redrive?note=...`
- Keep API response contracts machine-readable: route by `error.code`, not by message text.
- For supported-path incidents, use admin APIs/CLI only (do **not** inspect SQLite tables directly).

### End-to-end operator flow (supported Jira + ServiceNow path)

The following flow is designed to be complete for incident handling without opening SQLite directly.

#### 1) Startup configuration validation

```bash
export SENA_BASE_URL="${SENA_BASE_URL:-http://127.0.0.1:8000}"
export SENA_ADMIN_API_KEY="${SENA_ADMIN_API_KEY:?set admin key}"
export CONNECTOR="${CONNECTOR:-jira}" # or servicenow

sena production-check --format both
curl -fsS "$SENA_BASE_URL/v1/health" -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
curl -fsS "$SENA_BASE_URL/v1/ready" -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
```

Expected: `/v1/health.status=ok` and `/v1/ready.status=ready`.

#### 2) Normal health checks (steady state)

```bash
curl -fsS "$SENA_BASE_URL/v1/health" -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
curl -fsS "$SENA_BASE_URL/v1/ready" -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
curl -fsS "$SENA_BASE_URL/v1/integrations/$CONNECTOR/admin/outbound/duplicates/summary" \
  -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
```

Use the duplicate summary trend as an early warning for repeated webhook deliveries or repeated outbound retries.

#### 3) Outbound completion inspection

```bash
curl -fsS "$SENA_BASE_URL/v1/integrations/$CONNECTOR/admin/outbound/completions?limit=50" \
  -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
```

Interpretation:
- `operation_key`: deterministic key for a connector action (dedupe boundary).
- `target`: Jira (`comment` or `status`) or ServiceNow (`callback`).
- `attempts` close to `max_attempts`: reliability pressure even when eventually completed.
- `result`: remote-system callback response (authoritative outcome details).

#### 4) Dead-letter inspection

```bash
curl -fsS "$SENA_BASE_URL/v1/integrations/$CONNECTOR/admin/outbound/dead-letter?limit=50" \
  -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
```

Prioritize by:
- newest first (returned `id` descending),
- repeated `error` patterns,
- `attempts == max_attempts` (exhausted retries).

#### 5) Replay dead-letter item (preferred recovery)

After root-cause fix (credential, endpoint, mapping, remote-system outage):

```bash
export DEAD_LETTER_ID=123
curl -fsS -X POST \
  "$SENA_BASE_URL/v1/integrations/$CONNECTOR/admin/outbound/dead-letter/replay" \
  -H "x-api-key: $SENA_ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d "[$DEAD_LETTER_ID]" | jq .
```

Expected per item: `{"dead_letter_id":123,"status":"replayed",...}` and the item is removed from dead-letter.

#### 6) Manual redrive (only when replay is not possible)

Use when delivery already happened outside SENA and you must reconcile reliability state:

```bash
export DEAD_LETTER_ID=123
curl -fsS -X POST \
  "$SENA_BASE_URL/v1/integrations/$CONNECTOR/admin/outbound/dead-letter/manual-redrive?note=external-redrive-INC1234" \
  -H "x-api-key: $SENA_ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d "[$DEAD_LETTER_ID]" | jq .
```

Expected per item: `{"dead_letter_id":123,"status":"manually_redriven"}`.

#### 7) Duplicate suppression interpretation

```bash
curl -fsS "$SENA_BASE_URL/v1/integrations/$CONNECTOR/admin/outbound/duplicates/summary" \
  -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
```

Interpretation guide:
- `inbound.seen_total - inbound.unique_delivery_ids` approximates duplicate webhook deliveries observed.
- `inbound.suppressed_total` counts inbound duplicates safely ignored by idempotency.
- `outbound.suppressed_total` counts outbound duplicate sends prevented.
- `outbound.by_target` isolates suppression by delivery target (`comment`, `status`, `callback`).

## 8) API surface reminders

- versioned API endpoints under `/v1/*`
- unversioned compatibility routes are removed and return deprecation error payloads.

### Gated promotion flow example

Use `examples/gated_promotion_flow.sh` to see a complete operator flow:
1. register and promote to `candidate`,
2. fail promotion to `active` due to missing simulation evidence,
3. pass promotion with validation artifact + scenario simulation evidence.

## 9) Boundaries

Supported product path:
- `src/sena/policy/*`
- `src/sena/engine/*`
- `src/sena/api/*`
- `src/sena/cli/*`
- Integration runbooks in scope: Jira + ServiceNow (`/v1/integrations/jira/webhook`, `/v1/integrations/servicenow/webhook`)

Legacy/historical path (not supported for enterprise use):
- `src/sena/legacy/*`

Experimental integration surfaces (evaluation-only, no compatibility guarantees):
- `/v1/integrations/webhook`
- `/v1/integrations/slack/interactions`

## 10) Observability design (logs, metrics, tracing, alerts)

### Structured logs

Every request emits JSON logs with:
- request correlation: `request_id`, `trace_id`, `span_id`
- HTTP context: `method`, `path`, `status_code`, `duration_ms`
- decision context when applicable: `decision_id`, `outcome`, `policy_bundle`, `evaluation_ms`, `endpoint`
- failure context: `error_code`, `errors`

Operator usage:
- join logs by `request_id` for API incident triage;
- join cross-system requests by `trace_id` (propagated via `traceparent` and echoed in response headers).

### Metrics that matter

Prometheus endpoints: `/metrics`, `/v1/metrics/prometheus`.

Key metrics:
- availability/traffic:
  - `request_count_total{method,path,status_code}`
  - `request_duration_seconds_bucket{method,path}`
  - `api_errors_total{path,error_code,status_code}`
- policy decision quality and latency:
  - `sena_decisions_total{outcome,policy}`
  - `sena_evaluation_seconds_bucket`
  - `sena_active_policies`
- audit integrity:
  - `sena_audit_entries_total`
  - `sena_merkle_root_timestamp`
  - `sena_verification_requests_total`
  - `sena_verification_failures_total`
  - `sena_audit_verification_passed`

### Tracing

SENA now supports trace correlation at the HTTP edge:
- accepts inbound W3C `traceparent` header;
- if absent/invalid, generates `trace_id` + `span_id`;
- returns `traceparent` and `x-trace-id` response headers for downstream correlation.

This is sufficient for log/metric correlation without requiring a full OpenTelemetry backend.

### Alert thresholds (starter SLO-driven defaults)

- **API availability (critical)**: 5xx ratio > 1% for 5 minutes on evaluation endpoints.
- **Latency (warning/critical)**:
  - warning: p95 `request_duration_seconds` > 250ms for 10 minutes;
  - critical: p95 > 1s for 5 minutes.
- **Policy evaluation (critical)**: p95 `sena_evaluation_seconds` > 500ms for 10 minutes.
- **Error storms (critical)**: `api_errors_total{error_code="timeout"}` increases > 20 in 5 minutes.
- **Rate limiting pressure (warning)**: `api_errors_total{error_code="rate_limited"}` ratio > 5% for 10 minutes.
- **Audit integrity (critical)**:
  - `sena_audit_verification_passed == 0` for 2 consecutive checks;
  - any increase in `sena_verification_failures_total`.
- **Audit freshness (critical)**: `time() - sena_merkle_root_timestamp > 300` for active systems.
- **Auto-recovery trigger (critical)**: alert on `policy.automatic_recovery` webhook events.

## 11) Policy registry backup, restore, and disaster recovery runbook

Use this runbook for sqlite-backed policy registry deployments (`SENA_POLICY_STORE_BACKEND=sqlite`) and JSONL audit chains.

### Backup workflow (machine-readable artifacts)

Create a backup bundle containing:
- sqlite snapshot (`*.db`)
- manifest with backup checksum + sqlite `integrity_check`
- optional audit-chain snapshot (`*.audit.jsonl`)

```bash
python scripts/backup_policy_registry.py \
  --sqlite-path /var/lib/sena/policy-registry.db \
  --output-db /var/backups/sena/policy-registry-$(date -u +%Y%m%dT%H%M%SZ).db \
  --audit-chain /var/log/sena/audit.jsonl
```

Equivalent CLI wiring:

```bash
python -m sena.cli.main registry \
  --sqlite-path /var/lib/sena/policy-registry.db \
  backup \
  --output-db /var/backups/sena/policy-registry-$(date -u +%Y%m%dT%H%M%SZ).db \
  --audit-chain /var/log/sena/audit.jsonl
```

### Restore + verification workflow

Restore is fail-closed and machine-checks all required outcomes:
1. **DB backup integrity check** (`PRAGMA integrity_check` on backup before restore).
2. **Post-restore active bundle validation** (active bundle exists, includes rules, and rule hashes/digests match).
3. **Audit chain verification** (`verify_audit_chain` on restored audit file).
4. **Bundle signature verification where configured**:
   - always checks that `signature_verification_strict=true` bundles are marked verified;
   - optionally runs full manifest cryptographic verification when `--policy-dir` and `--keyring-dir` are provided.

```bash
python scripts/restore_policy_registry.py \
  --backup-db /var/backups/sena/policy-registry-20260401T000000Z.db \
  --backup-manifest /var/backups/sena/policy-registry-20260401T000000Z.db.manifest.json \
  --backup-audit /var/backups/sena/policy-registry-20260401T000000Z.db.audit.jsonl \
  --restore-db /var/lib/sena/policy-registry.db \
  --restore-audit /var/log/sena/audit.jsonl \
  --policy-dir /srv/sena/policies \
  --keyring-dir /srv/sena/keyring
```

Equivalent CLI wiring:

```bash
python -m sena.cli.main registry --sqlite-path /var/lib/sena/policy-registry.db restore \
  --backup-db /var/backups/sena/policy-registry-20260401T000000Z.db \
  --backup-manifest /var/backups/sena/policy-registry-20260401T000000Z.db.manifest.json \
  --backup-audit /var/backups/sena/policy-registry-20260401T000000Z.db.audit.jsonl \
  --restore-db /var/lib/sena/policy-registry.db \
  --restore-audit /var/log/sena/audit.jsonl
```

On any verification failure, restore exits non-zero and includes machine-parseable check output.

## 12) Audit operations (pilot-grade)

Use the audit CLI for operator workflows:

```bash
python -m sena.cli.main audit --audit-path /var/log/sena/audit.jsonl verify
python -m sena.cli.main audit --audit-path /var/log/sena/audit.jsonl summarize
python -m sena.cli.main audit --audit-path /var/log/sena/audit.jsonl locate-decision dec_abc123
```

- `verify`: validates chain continuity, storage sequence continuity, manifest integrity, and rotated-segment consistency.
- `summarize`: quick status, record counts, head hash, segment count, and first/last decision ids.
- `locate-decision`: finds the decision id and returns record index, segment location, sequence number, and chain links for rapid incident triage.

Corruption diagnostics are precise and actionable, with record and segment identifiers (for example: malformed record location, missing segment file, manifest sequence mismatch).
