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
| `production` | hardened runtime | mandatory auth, audit sink, strict signature verification, keyring, Jira secret when Jira webhook enabled |

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
  - `SENA_JIRA_WEBHOOK_SECRET` when Jira mapping is enabled

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
  - roles: `admin`, `policy_author`, `evaluator`

### Request safety controls

- `SENA_RATE_LIMIT_REQUESTS`
- `SENA_RATE_LIMIT_WINDOW_SECONDS`
- `SENA_REQUEST_MAX_BYTES`
- `SENA_REQUEST_TIMEOUT_SECONDS`

### Release signing and integrity

- `SENA_BUNDLE_RELEASE_MANIFEST_FILENAME` (default: `release-manifest.json`)
- `SENA_BUNDLE_SIGNATURE_STRICT`: require manifest verification
- `SENA_BUNDLE_SIGNATURE_KEYRING_DIR`: keyring directory for verification

### Audit sink

- `SENA_AUDIT_SINK_JSONL`: file path to append audit records
- `SENA_AUDIT_VERIFY_ON_STARTUP_STRICT`: when `true`, startup runs full chain verification across rotated segments and fails closed on corruption/mismatch

### Integrations

- `SENA_WEBHOOK_MAPPING_CONFIG`
- `SENA_JIRA_MAPPING_CONFIG`
- `SENA_JIRA_WEBHOOK_SECRET`
- `SENA_SERVICENOW_MAPPING_CONFIG`
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

## 8) API surface reminders

- versioned API endpoints under `/v1/*`
- unversioned compatibility routes are removed and return deprecation error payloads.

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

## 10) Policy registry backup, restore, and disaster recovery runbook

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

## 11) Audit operations (pilot-grade)

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
