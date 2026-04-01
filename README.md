# SENA

SENA is an **alpha deterministic policy-enforcement engine for AI-assisted enterprise approval workflows**.

It evaluates high-risk workflow actions against structured policy bundles and returns an auditable decision (`APPROVED`, `BLOCKED`, `ESCALATE_FOR_HUMAN_REVIEW`) with reasoning and machine-readable traces.

## Why centralizing control in SENA beats embedded per-tool rules

SENA is explicitly designed to outperform embedding approval rules directly inside Jira workflows, ServiceNow Flow Designer, or GRC-specific rule engines:

- **Cross-system normalization:** both Jira and ServiceNow events are normalized into one approval model before policy evaluation.
- **Portable policy packs:** one bundle can govern multiple source systems with only mapping-layer changes.
- **Deterministic simulation:** compare baseline vs candidate bundle and see exactly which historical scenarios change, grouped by source system/workflow/risk category.
- **Risk/compliance explainability:** every decision includes reviewer-focused rationale, matched control details, and provenance (bundle version + decision hash + input fingerprint).
- **Portable provenance:** the same bundle/control logic can be evidenced across systems with stable audit artifacts.

## Current maturity focus

We are prioritizing depth to move from alpha toward enterprise-credible pilots:
- 1–2 killer integrations (Stripe webhook decisioning, Jira approval-gating webhook, + Slack human escalation loop),
- a defensible policy lifecycle (diff/simulation/promotion gates),
- failure-mode and migration testing,
- durable audit + persistence guarantees.

See the opinionated implementation plan: [`docs/TECHNICAL_MATURITY_PLAN.md`](docs/TECHNICAL_MATURITY_PLAN.md).

Policy schema evolution and migration guidance: [`docs/POLICY_SCHEMA_EVOLUTION.md`](docs/POLICY_SCHEMA_EVOLUTION.md).

## Version

Current package/API version: `0.3.0` (single source: `src/sena/__init__.py`).

## Supported product path

- Policy parsing/validation/interpreter: `src/sena/policy/*`
- Deterministic evaluator: `src/sena/engine/*`
- API and CLI: `src/sena/api/*`, `src/sena/cli/*`

Legacy modules under `src/sena/legacy/*` are historical and out of supported scope.


## What is NOT part of the product

The following modules are **not** part of the supported SENA product path:

- Anything under `sena.legacy.*` / `src/sena/legacy/*`
- Compatibility shims that proxy to legacy code:
  - `sena.core.types`
  - `sena.orchestrator.sena`
  - `sena.evolutionary.deap_adapter`
  - `sena.llm.simulated_adapter`
  - `sena.production_systems.experta_adapter`

Runtime guardrails:

- Legacy imports always emit deprecation warnings in non-strict modes.
- `SENA_STRICT_LEGACY_IMPORTS=true` blocks legacy imports with `ImportError`.
- `SENA_RUNTIME_MODE=production` blocks `sena.legacy` imports with `RuntimeError` by default.
- `SENA_ALLOW_LEGACY_IN_PRODUCTION=true` is an explicit temporary override for controlled migrations only.

## Install

```bash
pip install -e .
pip install -e .[api,dev]  # optional API + test tooling
```

## Run tests

```bash
pytest
```

Coverage report target is configured at **80%** for the `sena` package via Coverage.py settings (`tool.coverage.report.fail_under`).

## CLI quickstart

```bash
python -m sena.cli.main \
  src/sena/examples/scenarios/demo_vendor_payment_block_unverified.json \
  --json
```

## Policy authoring workflow

```bash
# Create a starter bundle with editable templates
PYTHONPATH=src python -m sena.cli.main policy init ./my-policy-bundle

# Validate syntax + coverage
PYTHONPATH=src python -m sena.cli.main policy validate --policy-dir ./my-policy-bundle

# Run expected-outcome tests
PYTHONPATH=src python -m sena.cli.main policy test   --policy-dir ./my-policy-bundle   --test-file ./my-policy-bundle/tests/policy_tests.json

# Inspect schema version and compatibility
PYTHONPATH=src python -m sena.cli.main policy schema-version --policy-dir ./my-policy-bundle
PYTHONPATH=src python -m sena.cli.main policy verify-compatibility --policy-dir ./my-policy-bundle

# Preview and apply deterministic schema migration
PYTHONPATH=src python -m sena.cli.main policy migrate --policy-dir ./my-policy-bundle --dry-run
PYTHONPATH=src python -m sena.cli.main policy migrate --policy-dir ./my-policy-bundle
```

Generated templates include:
- `bundle.yaml`
- `payments.yaml`
- `tests/policy_tests.json`

## API quickstart

### Local

```bash
python -m uvicorn sena.api.app:app --reload
```

Versioned endpoints:
- `GET /v1/health`
- `GET /v1/ready`
- `GET /v1/bundle`
- `GET /v1/bundle/inspect`
- `POST /v1/evaluate`
- `POST /v1/integrations/webhook`
- `POST /v1/integrations/slack/interactions`
- `POST /v1/integrations/jira/webhook`
- `POST /v1/integrations/servicenow/webhook`
- `POST /v1/evaluate/batch`
- `POST /v1/simulation`
- `POST /v1/bundle/diff`
- `POST /v1/bundle/promotion/validate`
- `POST /v1/bundle/register`
- `POST /v1/bundle/promote`
- `GET /v1/audit/verify`
- `GET /metrics` (Prometheus exposition)

### API versioning policy

- SENA enforces explicit major-version routing via `/v{major}`.
- Current supported API surface is `/v1/*` only.
- Unversioned routes (`/health`, `/bundle`, `/evaluate`) were removed on **April 1, 2026** and now return `410 Gone`.
- Deprecated-route responses include migration headers:
  - `Deprecation: true`
  - `Sunset: 2026-04-01`
  - `Warning: 299` with migration guidance
  - `Link` with deprecation policy reference

### API error contract and code catalog

All API errors now return a consistent envelope:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "request_id": "req_abcd1234",
    "timestamp": "2026-04-01T00:00:00+00:00",
    "details": []
  }
}
```

Standard error codes:

- `validation_error` (422)
- `invalid_content_length` (400)
- `payload_too_large` (413)
- `unauthorized` (401)
- `forbidden` (403)
- `rate_limited` (429)
- `timeout` (504)
- `policy_store_unavailable` (400)
- `bundle_not_found` (404)
- `active_bundle_not_found` (404)
- `promotion_validation_failed` (400)
- `evaluation_error` (400)
- `webhook_mapping_not_configured` (400)
- `webhook_mapping_error` (400)
- `webhook_evaluation_error` (400)
- `jira_unsupported_event_type` (400)
- `jira_missing_required_fields` (400)
- `jira_duplicate_delivery` (200)
- `slack_interaction_error` (400)
- `audit_sink_not_configured` (400)

### Persistent policy registry (SQLite)

You can optionally run the API against a DB-backed policy registry instead of filesystem bundles.

The persistence layer now uses an explicit repository abstraction and versioned migration ledger designed to keep SQLite reliable today while enabling a PostgreSQL adapter without policy-lifecycle rewrites. See `docs/PERSISTENCE_ARCHITECTURE.md` for details.

```bash
# 1) Initialize schema
PYTHONPATH=src python scripts/migrate_policy_registry.py --sqlite-path ./.data/policy_registry.db

# 2) Start API in sqlite mode
export SENA_POLICY_STORE_BACKEND=sqlite
export SENA_POLICY_STORE_SQLITE_PATH=./.data/policy_registry.db
export SENA_BUNDLE_NAME=enterprise-compliance-controls
python -m uvicorn sena.api.app:app --reload

# 3) Register and promote a bundle through lifecycle states
curl -X POST http://127.0.0.1:8000/v1/bundle/register \
  -H 'content-type: application/json' \
  -d '{"policy_dir":"src/sena/examples/policies","bundle_name":"enterprise-compliance-controls","bundle_version":"2026.03","lifecycle":"draft"}'

curl -X POST http://127.0.0.1:8000/v1/bundle/promote \
  -H 'content-type: application/json' \
  -d '{"bundle_id":1,"target_lifecycle":"candidate"}'

curl -X POST http://127.0.0.1:8000/v1/bundle/promote \
  -H 'content-type: application/json' \
  -d '{"bundle_id":1,"target_lifecycle":"active"}'

# 4) Inspect currently active bundle
curl http://127.0.0.1:8000/v1/bundles/active
```


### Webhook integration layer

Use `POST /v1/integrations/webhook` to ingest external events (for example Stripe, Jira, or payment gateways), map them to an `ActionProposal`, and receive SENA decision output plus reasoning in one call.

Configure webhook mappings with `SENA_WEBHOOK_MAPPING_CONFIG` pointing to a JSON file.

Example mapping config: `src/sena/examples/integrations/webhook_mappings.yaml`

Stripe payment approval example:

```bash
curl -X POST http://127.0.0.1:8000/v1/integrations/webhook \
  -H 'content-type: application/json' \
  -d '{
    "provider":"stripe",
    "event_type":"payment_intent.created",
    "payload":{
      "id":"evt_123",
      "data":{"object":{"amount":25000,"currency":"usd","metadata":{"vendor_verified":false,"requester_role":"finance_analyst","requested_by":"user_9"}}}
    }
  }'
```

### Jira approval-gating integration

SENA supports a first-class Jira integration for deterministic approval workflows. Jira issue webhook events are normalized into `ActionProposal` objects, evaluated, and can be written back as comments/status payloads.

- Endpoint: `POST /v1/integrations/jira/webhook`
- Mapping config env: `SENA_JIRA_MAPPING_CONFIG`
- Webhook authenticity contract: pluggable verifier (`SENA_JIRA_WEBHOOK_SECRET` for shared-secret mode)
- Example mapping: `src/sena/examples/integrations/jira_mappings.yaml`
- Full runbook: `docs/integrations/JIRA.md`

### ServiceNow change approval integration

SENA supports a first-class ServiceNow change approval integration for enterprise governance workflows. ServiceNow events are normalized into the same approval-event model used by Jira, mapped into `ActionProposal`, and evaluated with deterministic callback payloads for workflow consumption.

- Endpoint: `POST /v1/integrations/servicenow/webhook`
- Mapping config env: `SENA_SERVICENOW_MAPPING_CONFIG`
- Example mapping: `src/sena/examples/integrations/servicenow_mappings.yaml`
- Full runbook: `docs/integrations/SERVICENOW.md`

### Slack human-escalation integration

SENA can automatically post Slack approval cards when a policy decision results in `ESCALATE_FOR_HUMAN_REVIEW`.

1) Configure Slack env vars:

```bash
export SENA_SLACK_BOT_TOKEN='xoxb-...'
export SENA_SLACK_CHANNEL='#risk-reviews'
```

2) Ensure your Slack app/bot has `chat:write` scope and is invited to the target channel.

3) Start the API and trigger an escalation via `/v1/evaluate` or `/v1/integrations/webhook`.

The posted message includes `Approve` and `Reject` buttons with deterministic action IDs:
- `sena_escalation_approve`
- `sena_escalation_reject`

To receive callbacks from those buttons, configure Slack Interactivity Request URL to:

`POST /v1/integrations/slack/interactions`

Example local callback target:

```text
https://<your-host>/v1/integrations/slack/interactions
```

### Quickstart (guaranteed working)

The commands below were validated against the checked-in example bundle and scenario paths, without requiring optional API dependencies.

```bash
# 1) Deterministic CLI evaluation using packaged examples
PYTHONPATH=src python -m sena.cli.main \
  src/sena/examples/scenarios/demo_vendor_payment_block_unverified.json \
  --json

# 2) End-to-end compare + simulation flow on known-good scenarios
PYTHONPATH=src python -m sena.cli.main \
  src/sena/examples/scenarios/demo_vendor_payment_block_unverified.json \
  --compare-policy-dir src/sena/examples/policies \
  --simulate-scenarios src/sena/examples/scenarios/simulation_scenarios.json \
  --json
```

Simulation output includes `grouped_changes` by:
- `source_system`
- `workflow_stage`
- `risk_category`

### Docker

```bash
# API only (default)
docker compose up --build sena-api

# API + optional postgres sidecar (profile: db)
docker compose --profile db up --build
```

The API image is production-oriented: slim base image, dedicated non-root user, and a built-in `/v1/health` container health check.

`docker-compose.yml` also includes:
- API health check (`/v1/health`)
- Optional Postgres service (`sena-db`) behind the `db` profile with `pg_isready` health checks
- A persisted `/data` volume for SQLite-backed policy registry mode

## Security and governance baseline (alpha)

- Optional API key RBAC middleware:
  - single key: `SENA_API_KEY_ENABLED=true`, `SENA_API_KEY=...` (implicit `admin` role)
  - multi-key RBAC: `SENA_API_KEYS=admin_key:admin,author_key:policy_author,eval_key:evaluator`
- Per-key fixed-window rate limiting (`SENA_RATE_LIMIT_REQUESTS`, `SENA_RATE_LIMIT_WINDOW_SECONDS`).
- Request payload size cap (`SENA_REQUEST_MAX_BYTES`) with explicit `413` failure.
- Request timeout guardrail (`SENA_REQUEST_TIMEOUT_SECONDS`) with explicit `504` failure.
- Request ID propagation (`x-request-id`) for traceability.
- Pluggable audit sinks via `sena.audit.sinks` with JSONL file and S3-compatible backends.
- Optional JSONL audit sink (`SENA_AUDIT_SINK_JSONL=/path/to/audit.jsonl`) with tamper-evident hash chaining + verification endpoint/CLI.
- Audit sink controls: append-only mode, file rotation, and retention policies for enterprise governance.
- Bundle manifest lifecycle states (`draft` / `candidate` / `active` / `deprecated`) and promotion validation tooling.
- Bundle-to-bundle simulation and impact analysis via API and CLI.
- Grouped simulation change reports by source system/workflow/risk category for policy-release evidence.
- Signed release manifests for bundles with CLI generation/sign/verification and strict promotion gates (see `docs/BUNDLE_SIGNING.md`).
- Deterministic DSL extensions (`starts_with`, `ends_with`, `matches_regex`, `exists`, `between`) and optional context schema checks.

## Documentation

- Architecture: `docs/ARCHITECTURE.md`
- Normalized approval contract: `docs/NORMALIZED_APPROVAL_MODEL.md`
- Portable pack example (Jira + ServiceNow): `docs/examples/portable_policy_pack_jira_servicenow.md`
- Control plane capabilities and alpha boundaries: `docs/CONTROL_PLANE.md`
- Operations/deployment: `docs/OPERATIONS.md`
- Deployment profiles (dev/pilot/production-like): `docs/DEPLOYMENT_PROFILES.md`
- Legacy migration boundary: `docs/MIGRATION.md`
- Gap analysis: `ENTERPRISE_GAP_ANALYSIS.md`
- Changelog: `CHANGELOG.md`

## Alpha honesty

SENA is not yet a full enterprise platform. It does **not** currently provide HA multi-region control plane, OIDC/SSO, tenant isolation, policy authoring UI, durable DB-backed lifecycle workflow state, or formal compliance certification claims.
