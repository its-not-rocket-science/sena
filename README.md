# SENA

SENA is an **alpha deterministic Jira + ServiceNow approval decisioning engine with replayable audit evidence**.

Read `docs/READINESS.md` for explicit capability status by maturity level (implemented now, pilot-ready, and not yet production-grade).

The supported product path is intentionally narrow and implementation-backed: normalize Jira/ServiceNow approval payloads, evaluate them against versioned policy bundles, and return deterministic decisions plus replayable evidence artifacts.

## Supported product path (default)

If you only read one section, read this one.

## Flagship workflow (start here)

Run one realistic end-to-end workflow first: **ServiceNow emergency privileged change approval**.

- Docs: `docs/FLAGSHIP_WORKFLOW.md`
- Runnable example: `examples/flagship/`
- Outcome: deterministic `BLOCKED` decision with replay + audit verification artifacts

Quick run:

```bash
PYTHONPATH=src python examples/flagship/run_flagship.py
```

- Decision outcomes: `APPROVED`, `BLOCKED`, `ESCALATE_FOR_HUMAN_REVIEW`
- One normalized policy model across Jira and ServiceNow
- Deterministic replay contract + hash-linked audit chain

Supported code path:
- `src/sena/policy/*`
- `src/sena/engine/*`
- `src/sena/api/*`
- `src/sena/cli/*`
- `src/sena/audit/*`
- `src/sena/integrations/jira.py`
- `src/sena/integrations/servicenow.py`

Start here for supported docs and operator flow:
- `docs/FLAGSHIP_WORKFLOW.md`
- `docs/INDEX.md`
- `docs/ASYNC_EXECUTION.md`
- `docs/CONTROL_PLANE.md`
- `docs/READINESS.md`
- `docs/ARCHITECTURE.md`
- `examples/README.md` (supported examples first)

## Explicit scope boundaries

Maturity labels are normative: treat only what is marked pilot-ready in `docs/READINESS.md` as suitable for pilot deployment.

- **supported:** Jira + ServiceNow decisioning and evidence path above.
- **experimental:** generic webhook, Slack interactions, LangChain callback, and non-core modules listed in `src/sena/MODULE_STATUS.md`.
- **labs/demo:** investor/lab/k8s demo materials indexed in `docs/EXPERIMENTAL_INDEX.md`.
- **legacy:** historical material only; no product guarantees.

## Deterministic replay contract

SENA separates replay-stable and runtime-only data:
- `canonical_replay_payload`: replay-stable artifact for equality checks.
- `operational_metadata`: runtime-only values (for example `decision_id`, event/write timestamps).

Guarantees:
- **Outcome determinism**: identical normalized input + identical policy bundle version produce identical outcome.
- **Reasoning determinism (canonical)**: precedence steps, matched controls, and rationale in `canonical_replay_payload` are replay-stable.
- **Full raw trace determinism**: **not guaranteed** (operational metadata intentionally varies).

## Integration status

**Supported integrations (productized depth):**
- Jira webhook normalization + evaluation (`POST /v1/integrations/jira/webhook`)
- ServiceNow webhook normalization + evaluation (`POST /v1/integrations/servicenow/webhook`)

**Experimental integrations (evaluation only, subject to change):**
- Generic webhook mapping (`POST /v1/integrations/webhook`)
- Slack interactions (`POST /v1/integrations/slack/interactions`)
- LangChain callback interception (`sena.integrations.langchain.SenaApprovalCallback`)

## Version

Current package/API version: `0.3.0` (single source: `src/sena/__init__.py`).

## Install

```bash
pip install -e .
pip install -e .[api,dev]
pip install -e .[langchain]  # optional callback integration
```

## Local quality checks

```bash
ruff format --check src/sena tests --exclude src/sena/legacy
ruff check src tests
pytest
```

## CLI quickstart

```bash
python -m sena.cli.main \
  src/sena/examples/scenarios/demo_vendor_payment_block_unverified.json \
  --json
```

## API quickstart

```bash
python -m uvicorn sena.api.app:app --reload
```

Versioned endpoints are under `/v1/*`. OpenAPI is at `/openapi.json` and Swagger UI at `/docs`.

## Non-default indexes

- Experimental + labs index: `docs/EXPERIMENTAL_INDEX.md`
- Legacy/historical archive: `docs/archive/legacy_vision.md`
