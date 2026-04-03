# SENA

SENA is the first deterministic audit trail for AI agent decisions. When an AI approves a refund, modifies infrastructure, or grants access, SENA provides a cryptographically verifiable, replayable record of WHY. No other tool offers Merkle tree proofs for AI actions.

## Primary wedge (what to remember)

SENA’s product wedge is simple: **one normalized policy decision layer for Jira + ServiceNow approval events**.

Teams use SENA to evaluate high-risk actions (for example: change approvals, vendor payments, sensitive exports) against versioned policy bundles and get deterministic outcomes with machine-readable evidence.

- Decision outcomes: `APPROVED`, `BLOCKED`, `ESCALATE_FOR_HUMAN_REVIEW`
- Same normalized policy model across systems
- Deterministic trace + audit chain for replay and review

## Repository truth source

When docs drift, treat these as canonical in this order:

1. `README.md` (positioning + boundaries)
2. `docs/CONTROL_PLANE.md` (implemented product surface)
3. `docs/ARCHITECTURE.md` (supported-vs-legacy architecture reality)
4. `docs/TECHNICAL_MATURITY_PLAN.md` (alpha → pilot-ready plan)
5. `ROADMAP.md` (next priorities and non-goals)

## What SENA is

- A deterministic policy decision engine for AI-assisted workflow actions.
- A normalized approval model across Jira and ServiceNow.
- A policy bundle lifecycle with diff/simulation/promotion validation.
- An evidence layer (trace, provenance, hash-linked audit records).

## What SENA is not

- Not a formal verification platform.
- Not a generalized “safe AI” suite.
- Not a broad connector marketplace in the current phase.
- Not a full enterprise control plane yet (no built-in multi-tenant RBAC/OIDC admin UI).

## Integration status

**Supported integrations today (productized depth):**
- Jira webhook normalization + evaluation (`POST /v1/integrations/jira/webhook`)
- ServiceNow webhook normalization + evaluation (`POST /v1/integrations/servicenow/webhook`)

**Experimental integrations (evaluation only, subject to change):**
- Generic webhook mapping (`POST /v1/integrations/webhook`)
- Slack interactions (`POST /v1/integrations/slack/interactions`)
- LangChain callback interception (`sena.integrations.langchain.SenaApprovalCallback`)

## Maturity snapshot (April 2026)

SENA is **alpha**.

Implemented in the supported path (`src/sena/*`):
- deterministic parser/validator/interpreter/evaluator pipeline,
- normalized Jira/ServiceNow integration routes,
- bundle diff, simulation, promotion-validation APIs,
- hash-linked JSONL audit chain with verification endpoint,
- CLI and API surfaces for evaluate/replay/simulation/lifecycle flows.

Not yet pilot-ready by default:
- transactional multi-tenant control plane,
- built-in OIDC/RBAC admin plane,
- replicated/WORM-native audit storage,
- asynchronous long-running simulation job orchestration,
- full policy authoring UI.

## Top 3 roadmap priorities

1. Harden Jira + ServiceNow production runbooks and fixture coverage.
2. Enforce fail-closed active promotion gates with required simulation and evidence artifacts.
3. Raise operational maturity for pilot readiness (SQLite durability, restore drills, audit archive recovery verification).

## Supported product path

- Policy parsing/validation/interpreter: `src/sena/policy/*`
- Deterministic evaluator: `src/sena/engine/*`
- API and CLI: `src/sena/api/*`, `src/sena/cli/*`
- Integrations (supported depth): `src/sena/integrations/jira.py`, `src/sena/integrations/servicenow.py`

Legacy modules under `src/sena/legacy/*` are out of supported scope.

## Version

Current package/API version: `0.3.0` (single source: `src/sena/__init__.py`).

## Install

```bash
pip install -e .
pip install -e .[api,dev]
pip install -e .[langchain]  # optional callback integration
```

## Run tests

```bash
pytest
```

## Local quality checks

```bash
ruff format --check src/sena tests --exclude src/sena/legacy
ruff check src/sena tests
pytest
```

See `CONTRIBUTING.md` for contributor workflow and local quality guidance.

## Pilot acceptance evidence

Define and verify "good enough for pilot" using:

- Criteria + checklist: `docs/PILOT_ACCEPTANCE.md`
- Reproducible evidence command: `make pilot-evidence`
- End-to-end integration pack command: `make pilot-integration-pack`
- Sample committed bundle: `docs/examples/pilot_evidence_sample/`

## Failure-mode coverage matrix

| Area | Coverage status | Details |
|---|---|---|
| Deterministic governance failure modes | Expanded | See `docs/FAILURE_MODE_MATRIX.md` for tested vs not-yet-tested classes and stable error contracts. |

## 15-minute canonical integration quickstart

Run the design-partner-grade ServiceNow pack (with Jira portability proof):

```bash
PYTHONPATH=src python examples/design_partner_reference/run_reference.py
examples/design_partner_reference/demo_15m.sh
```

What you should see in `examples/design_partner_reference/artifacts/`:
- promotion gate evidence (`simulation-report.json`, `promotion-validation.json`),
- deterministic replay evidence (`replay-report-stable.json`),
- policy-update drift evidence (`replay-report-policy-update.json`),
- audit verification (`audit-chain-verification.json`),
- normalized portability examples (`normalized-event-examples.json`).

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

Versioned endpoints are under `/v1/*`. OpenAPI is available at `/openapi.json` and Swagger UI at `/docs`.

If API key auth is enabled, send `X-API-Key: <key>` on every request.

Key endpoints:
- `POST /v1/evaluate`
- `POST /v1/evaluate/batch`
- `POST /v1/simulation`
- `POST /v1/replay/drift`
- `POST /v1/bundle/diff`
- `POST /v1/bundle/promotion/validate`
- `POST /v1/integrations/jira/webhook`
- `POST /v1/integrations/servicenow/webhook`
- `GET /v1/audit/verify`
- `POST /v1/audit/verify/tree` (Merkle proof verification for a single decision)
- `POST /v1/audit/hold/{decision_id}` (apply legal hold)
- `GET /v1/audit/hold` (list active legal holds)

Operational audit durability guidance (local sink + archive/restore drills):
- `docs/AUDIT_DURABILITY.md`
- `docs/BACKUP.md`
- `docs/DEPLOYMENT.md` (production deployment patterns)
- `docs/COOKBOOK.md` (copy/paste integration examples)

Experimental endpoints:
- `POST /v1/integrations/webhook`
- `POST /v1/integrations/slack/interactions`


## LangChain callback quickstart (experimental)

```python
from sena.integrations.langchain import SenaApprovalCallback

callbacks = [SenaApprovalCallback("http://localhost:8000", "enterprise-demo:active")]
```

See `examples/langchain_demo/refund_agent.py` and `examples/langchain_demo/verify_refund_audit.py` for an end-to-end audit-proof workflow.

## Investor Kubernetes admission demo

Run the end-to-end investor demo (AI suggestion -> SENA block -> Merkle verification):

```bash
make demo-k8s
```

Demo assets live in `examples/k8s_admission_demo/`:
- `ai_agent_simulator.py`
- `sena_webhook.py`
- `verify_demo.py`
- `docker-compose-demo.yml`
- `DEMO_SCRIPT.md`
- `INVESTOR_DECK.md`

## Investor monitoring demo (Prometheus + Grafana)

Run the monitoring stack and start continuous demo traffic:

```bash
make demo-monitoring
```

This starts SENA, Prometheus, and Grafana via `docker-compose-monitoring.yml`, and
generates traffic with `scripts/generate_traffic.py` (10 decisions/second with random
Merkle proof verification attempts).
