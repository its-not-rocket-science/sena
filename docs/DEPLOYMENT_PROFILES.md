# SENA Deployment Profiles

This guide now defines a single opinionated pilot profile for supported use cases:

- **Single-tenant (or tightly controlled tenant) operation**
- **Jira + ServiceNow connectors only**
- **Deterministic policy decisioning**
- **Replayable evidence and strict startup verification**
- **Durable inbound queue + persistent jobs**

## Profile A: Local development (fast feedback)

```bash
export SENA_RUNTIME_MODE=development
export SENA_API_HOST=0.0.0.0
export SENA_API_PORT=8000
export SENA_POLICY_STORE_BACKEND=filesystem
export SENA_POLICY_DIR=src/sena/examples/policies
export SENA_BUNDLE_NAME=enterprise-compliance-controls
export SENA_BUNDLE_VERSION=2026.03
export SENA_INGESTION_QUEUE_BACKEND=memory

python -m uvicorn sena.api.app:app --host 0.0.0.0 --port 8000
```

Notes:
- API key auth optional for local workflows.
- Signing strictness and audit sink are optional in this mode.
- Jira/ServiceNow webhook secrets are optional in this mode; if omitted, startup logs warnings that inbound events are forgeable.

## Profile B: Local containerized runtime

### Docker

```bash
docker build -t sena-api:local .

docker run --rm -p 8000:8000 \
  -e SENA_RUNTIME_MODE=pilot \
  -e SENA_API_KEY_ENABLED=true \
  -e SENA_API_KEY=pilot-local-key \
  -e SENA_POLICY_STORE_BACKEND=filesystem \
  -e SENA_POLICY_DIR=src/sena/examples/policies \
  -e SENA_INGESTION_QUEUE_BACKEND=sqlite \
  -e SENA_PROCESSING_SQLITE_PATH=/var/lib/sena/runtime.db \
  -e SENA_AUDIT_SINK_JSONL=/tmp/sena-audit/audit.jsonl \
  -e SENA_BUNDLE_SIGNATURE_STRICT=false \
  sena-api:local
```

### Docker Compose

Use the repository's `docker-compose.yml` as base and layer environment overrides for pilot/prod-like controls.

## Profile C: Credible pilot (recommended supported profile)

```bash
export SENA_DEPLOYMENT_PROFILE=credible_pilot
export SENA_RUNTIME_MODE=pilot
export SENA_API_KEY_ENABLED=true
export SENA_API_KEYS="author-key:policy_author,review-key:reviewer,deploy-key:deployer,audit-key:auditor,admin-key:admin"

export SENA_POLICY_STORE_BACKEND=sqlite
export SENA_POLICY_STORE_SQLITE_PATH=/var/lib/sena/policy_registry.db

export SENA_AUDIT_SINK_JSONL=/var/log/sena/audit.jsonl
export SENA_AUDIT_VERIFY_ON_STARTUP_STRICT=true
export SENA_INGESTION_QUEUE_BACKEND=sqlite
export SENA_PROCESSING_SQLITE_PATH=/var/lib/sena/runtime.db

export SENA_BUNDLE_SIGNATURE_STRICT=true
export SENA_BUNDLE_SIGNATURE_KEYRING_DIR=/etc/sena/keyring

export SENA_JIRA_MAPPING_CONFIG=/etc/sena/integrations/jira.yaml
export SENA_JIRA_WEBHOOK_SECRET='replace-with-secret'
export SENA_SERVICENOW_MAPPING_CONFIG=/etc/sena/integrations/servicenow.yaml
export SENA_SERVICENOW_WEBHOOK_SECRET='replace-with-secret'
export SENA_INTEGRATION_RELIABILITY_SQLITE_PATH=/var/lib/sena/integration_reliability.db
export SENA_ENABLE_EXPERIMENTAL_ROUTES=false
```

Mandatory invariants enforced at startup when `SENA_DEPLOYMENT_PROFILE=credible_pilot`:

- `SENA_RUNTIME_MODE=pilot`.
- API key auth enabled **with role-bound `SENA_API_KEYS`**.
- JWT auth disabled (avoid mixed auth model during pilot).
- `SENA_POLICY_STORE_BACKEND=sqlite`.
- `SENA_INGESTION_QUEUE_BACKEND=sqlite` (memory queue forbidden).
- `SENA_INTEGRATION_RELIABILITY_SQLITE_PATH` required, in-memory reliability forbidden.
- `SENA_AUDIT_SINK_JSONL` + `SENA_AUDIT_VERIFY_ON_STARTUP_STRICT=true`.
- `SENA_BUNDLE_SIGNATURE_STRICT=true` + `SENA_BUNDLE_SIGNATURE_KEYRING_DIR`.
- Jira and ServiceNow mappings + webhook secrets required.
- Generic webhook mapping and Slack integration forbidden.
- Experimental integration routes explicitly forbidden.

Validate the profile before deploy:

```bash
python -m sena.cli.main pilot-check --format both
```

## Profile D: Stricter production-like mode (fail-closed)

`SENA_RUNTIME_MODE=production` enforces:
- API auth enabled with configured keys
- audit sink configured
- strict release-signature verification enabled
- keyring directory configured and present
- Jira webhook secret mandatory if Jira integration is enabled
- ServiceNow webhook secret mandatory if ServiceNow integration is enabled
- durable ingestion queue backend mandatory (`memory` is rejected in production)

Example:

```bash
export SENA_RUNTIME_MODE=production
export SENA_API_KEY_ENABLED=true
export SENA_API_KEYS="ops-admin:admin,policy-ci:policy_author,review-svc:reviewer,deploy-svc:deployer,audit-svc:auditor"

export SENA_POLICY_STORE_BACKEND=sqlite
export SENA_POLICY_STORE_SQLITE_PATH=/var/lib/sena/policy_registry.db

export SENA_AUDIT_SINK_JSONL=/var/log/sena/audit/audit.jsonl

export SENA_BUNDLE_SIGNATURE_STRICT=true
export SENA_BUNDLE_SIGNATURE_KEYRING_DIR=/etc/sena/keyring
export SENA_BUNDLE_RELEASE_MANIFEST_FILENAME=release-manifest.json

export SENA_JIRA_MAPPING_CONFIG=/etc/sena/integrations/jira.yaml
export SENA_JIRA_WEBHOOK_SECRET='replace-with-rotated-secret'
```

## Integration secrets and key hygiene

- Use a secret manager; do not bake secrets into image or compose files.
- Rotate `SENA_API_KEY(S)` and integration webhook secrets on a fixed schedule.
- Use environment-specific keyrings for release signature verification.
- Enforce file permissions:
  - keyring dir: read-only to SENA runtime identity
  - audit sink dir: append/write for runtime identity only

## Mandatory preflight checks

Run before deployment:

```bash
sena production-check --format both
python -m sena.cli.main pilot-check --format both
```

For credible pilot rollouts, the pipeline must fail closed if either check exits non-zero.

See also: `docs/CREDIBLE_PILOT_PROFILE.md` for threat assumptions, non-guarantees, and operator checklist.
