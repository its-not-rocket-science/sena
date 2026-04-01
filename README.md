# SENA

SENA is an **alpha deterministic policy-enforcement engine for AI-assisted enterprise approval workflows**.

It evaluates high-risk workflow actions against structured policy bundles and returns an auditable decision (`APPROVED`, `BLOCKED`, `ESCALATE_FOR_HUMAN_REVIEW`) with reasoning and machine-readable traces.

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
- `POST /v1/evaluate/batch`
- `POST /v1/simulation`
- `POST /v1/bundle/diff`
- `POST /v1/bundle/promotion/validate`
- `POST /v1/bundle/register`
- `POST /v1/bundle/promote`
- `GET /v1/audit/verify`

Backward-compatible aliases still exist at `/health`, `/bundle`, `/evaluate`.

### Persistent policy registry (SQLite)

You can optionally run the API against a DB-backed policy registry instead of filesystem bundles.

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

### Docker

```bash
docker compose up --build
```

## Security and governance baseline (alpha)

- Optional shared API key middleware (`SENA_API_KEY_ENABLED=true`, `SENA_API_KEY=...`).
- Request ID propagation (`x-request-id`) for traceability.
- Optional JSONL audit sink (`SENA_AUDIT_SINK_JSONL=/path/to/audit.jsonl`) with tamper-evident hash chaining + verification endpoint/CLI.
- Bundle manifest lifecycle states (`draft` / `candidate` / `active` / `deprecated`) and promotion validation tooling.
- Bundle-to-bundle simulation and impact analysis via API and CLI.
- Deterministic DSL extensions (`starts_with`, `ends_with`, `matches_regex`, `exists`, `between`) and optional context schema checks.

## Documentation

- Architecture: `docs/ARCHITECTURE.md`
- Control plane capabilities and alpha boundaries: `docs/CONTROL_PLANE.md`
- Operations/deployment: `docs/OPERATIONS.md`
- Legacy migration boundary: `docs/MIGRATION.md`
- Gap analysis: `ENTERPRISE_GAP_ANALYSIS.md`
- Changelog: `CHANGELOG.md`

## Alpha honesty

SENA is not yet a full enterprise platform. It does **not** currently provide HA multi-region control plane, OIDC/SSO, tenant isolation, policy authoring UI, durable DB-backed lifecycle workflow state, or formal compliance certification claims.
