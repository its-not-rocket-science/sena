# SENA

SENA is an **alpha deterministic policy-enforcement engine for AI-assisted enterprise approval workflows**.

It evaluates high-risk workflow actions against structured policy bundles and returns an auditable decision (`APPROVED`, `BLOCKED`, `ESCALATE_FOR_HUMAN_REVIEW`) with reasoning and machine-readable traces.

## Supported product path

- Policy parsing/validation/interpreter: `src/sena/policy/*`
- Deterministic evaluator: `src/sena/engine/*`
- API and CLI: `src/sena/api/*`, `src/sena/cli/*`

Legacy modules under `src/sena/legacy/*` are historical and out of supported scope.

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
  --policy-dir src/sena/examples/policies \
  --policy-bundle-name enterprise-demo \
  --bundle-version 2026.03 \
  --json
```

## API quickstart

### Local

```bash
cp .env.example .env
python -m uvicorn sena.api.app:app --reload
```

Versioned endpoints:
- `GET /v1/health`
- `GET /v1/ready`
- `GET /v1/bundle`
- `GET /v1/bundle/inspect`
- `POST /v1/evaluate`
- `POST /v1/evaluate/batch`
- `POST /v1/simulation`
- `POST /v1/bundle/diff`
- `POST /v1/bundle/promotion/validate`
- `GET /v1/audit/verify`

Backward-compatible aliases still exist at `/health`, `/bundle`, `/evaluate`.

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

## Alpha honesty

SENA is not yet a full enterprise platform. It does **not** currently provide HA multi-region control plane, OIDC/SSO, tenant isolation, policy authoring UI, durable DB-backed lifecycle workflow state, or formal compliance certification claims.
