# SENA

SENA is the first deterministic audit trail for AI agent decisions. When an AI approves a refund, modifies infrastructure, or grants access, SENA provides a cryptographically verifiable, replayable record of WHY. No other tool offers Merkle tree proofs for AI actions.

## Primary wedge (what to remember)

SENA’s product wedge is simple: **one normalized policy decision layer for Jira + ServiceNow approval events**.

Teams use SENA to evaluate high-risk actions (for example: change approvals, vendor payments, sensitive exports) against versioned policy bundles and get deterministic outcomes with machine-readable evidence.

- Decision outcomes: `APPROVED`, `BLOCKED`, `ESCALATE_FOR_HUMAN_REVIEW`
- Same normalized policy model across systems
- Deterministic trace + audit chain for replay and review

## Deterministic replay contract

SENA now separates **canonical replay payloads** from **operational metadata**:

- `canonical_replay_payload`: replay-stable artifact for equality checks across runs.
- `operational_metadata`: runtime-only values (for example `decision_id`, event/write timestamps).

Deterministic guarantees are explicit:

- **Outcome determinism**: identical normalized input + identical policy bundle version produce identical outcome.
- **Reasoning determinism (canonical)**: precedence steps, matched controls, and rationale inside `canonical_replay_payload` are replay-stable.
- **Full raw trace determinism**: **not guaranteed** (operational metadata intentionally varies).

## Repository truth source

When docs drift, treat these as canonical in this order:

1. `README.md` (positioning + supported scope)
2. `docs/CONTROL_PLANE.md` (implemented product surface)
3. `docs/ARCHITECTURE.md` (supported vs experimental vs legacy boundaries)
4. `docs/TECHNICAL_MATURITY_PLAN.md` (alpha → pilot-ready execution plan)

Everything else is supplementary. Demo/investor materials are intentionally isolated in `docs/LABS.md`.

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

## Docs consistency report

See `docs/DOCS_CONSISTENCY_REPORT.md` for a summary of strategy-language alignment updates.

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
- A-grade trust rubric + gap roadmap: `docs/A_GRADE_PILOT_READY.md`
- A-grade 30-day transformation plan for first 3 customers: `docs/TRANSFORMATION_PLAN_30_DAY_A_GRADE.md`
- Reproducible evidence command: `make pilot-evidence`
- End-to-end integration pack command: `make pilot-integration-pack`
- Sample committed bundle: `docs/examples/pilot_evidence_sample/`

## Failure-mode coverage matrix

| Area | Coverage status | Details |
|---|---|---|
| Deterministic governance failure modes | Expanded | See `docs/FAILURE_MODE_MATRIX.md` for tested vs not-yet-tested classes and stable error contracts. |
| Jira + ServiceNow integration confidence | Enforced in CI | See `tests/fixtures/integrations/confidence_matrix.json` (generated from committed mappings + test-backed assertions). |

## Canonical workflow definition

For the single end-to-end workflow definition (steps, evidence, repository mapping, and gap list), see `docs/CANONICAL_WORKFLOW.md`.

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

### Enterprise adoption utilities

- Import existing policy definitions into SENA bundle format:
  - `python -m sena.cli.main policy import-legacy --source ./legacy_policies.yaml --output-dir ./bundle --bundle-name enterprise-controls --bundle-version 2026.04`
- Run legacy vs. new bundles in parallel and emit discrepancy report JSON:
  - `python -m sena.cli.main replay parallel-run --replay-file ./replay_cases.json --old-policy-dir ./legacy_bundle --new-policy-dir ./candidate_bundle`
- Export canonical replay artifact (stable hashes + provenance, volatile fields excluded):
  - `python -m sena.cli.main replay export-canonical ./scenario.json --policy-dir ./policies/active --output ./canonical-artifact.json`
- Resolve phased rollout mode by business unit and region:
  - `python -m sena.cli.main rollout resolve --config ./rollout.yaml --business-unit finance --region us-east-1`

Parallel-run discrepancy output format:
- `report_type: sena.parallel_run_discrepancy_report`
- `mode: parallel`
- `old_label`, `new_label`
- `discrepancy_summary` (`outcome_changes`, `matched_control_changes`, `missing_evidence_changes`)
- `discrepancies[]` entries with per-case old/new outcomes, control deltas, evidence deltas, and source metadata.

## API quickstart

```bash
python -m uvicorn sena.api.app:app --reload
```

Versioned endpoints are under `/v1/*`. OpenAPI is available at `/openapi.json` and Swagger UI at `/docs`.

If API key auth is enabled, send `X-API-Key: <key>` on every request.

Key endpoints:
- `POST /v1/evaluate`
- `POST /v1/exceptions/create`
- `POST /v1/exceptions/approve`
- `GET /v1/exceptions/active`
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
- `GET /v1/analytics/policy-efficacy` (policy efficacy metrics from downstream outcomes/incidents)
- `GET /v1/admin/data-access` (governed data access audit events)
- `GET /v1/admin/slo` (SLO targets for latency, availability, and durability)
- `GET /v1/admin/data/payloads?tenant_id=<id>&region=<region>` (tenant+region scoped governed payloads)
- `POST /v1/admin/data/payloads/{payload_id}/hold` (legal hold for governed payload retention)
- `GET /v1/decision/{decision_id}/explanation?view=analyst|auditor` (export concise or full decision explanation)

Webhook signature verification (production-focused behavior):
- Jira (`POST /v1/integrations/jira/webhook`)
  - Supported signature headers:
    - `x-sena-signature` (hex digest)
    - `x-hub-signature-256` (`sha256=<hex-digest>` or raw hex digest)
  - Supported algorithm: `HMAC-SHA256` over the raw request body bytes.
  - Secret rotation: when both `SENA_JIRA_WEBHOOK_SECRET` and `SENA_JIRA_WEBHOOK_SECRET_PREVIOUS` are configured, either secret is accepted.
  - Fail-closed behavior when secret verification is enabled: missing signature and invalid signature both return `401` with error code `jira_authentication_failed`.
- ServiceNow (`POST /v1/integrations/servicenow/webhook`)
  - Supported signature headers:
    - `x-sena-signature` (hex digest)
    - `x-servicenow-signature` (`sha256=<hex-digest>` or raw hex digest)
  - Supported algorithm: `HMAC-SHA256` over the raw request body bytes.
  - Secret rotation: when both `SENA_SERVICENOW_WEBHOOK_SECRET` and `SENA_SERVICENOW_WEBHOOK_SECRET_PREVIOUS` are configured, either secret is accepted.
  - Fail-closed behavior when secret verification is enabled: missing signature and invalid signature both return `401` with error code `servicenow_authentication_failed`.

Operational audit durability guidance (local sink + archive/restore drills):
- `docs/AUDIT_DURABILITY.md`
- `docs/BACKUP.md`
- `docs/DEPLOYMENT.md` (production deployment patterns)
- `docs/COOKBOOK.md` (copy/paste integration examples)
- `docs/TENANCY_MODEL.md` (tenant + region pinning, PII redaction, retention/legal hold model)
- `docs/SECURITY_DATA_FLOW_AND_THREAT_MODEL.md` (enterprise DFD + STRIDE threat model)
- `docs/INCIDENT_RESPONSE_AND_BREACH_NOTIFICATION.md` (incident response + breach notification process)
- `docs/VULNERABILITY_MANAGEMENT_AND_SUBPROCESSORS.md` (dependency scanning, patch cadence, subprocessors register)
- `docs/SECURITY_CHECKLIST.md` (release/readiness security checklist)

Experimental endpoints:
- `POST /v1/integrations/webhook`
- `POST /v1/integrations/slack/interactions`

`POST /v1/evaluate` also supports `simulate_exceptions: true` to return an explicit
comparison between baseline deterministic evaluation and exception-overlay results.
The same request may include optional `downstream_outcome` (`success` or `failure`)
and `incident_flag` fields for post-decision outcome tracking and analytics.

## Production reliability hardening

SENA now includes a reliability layer for production hardening:
- queue-based ingestion buffering (`memory` default, optional `redis` backend),
- circuit breakers for integration dependencies (Jira / ServiceNow / webhook),
- graceful degradation with deterministic `degraded` fallback payloads and DLQ retry records,
- explicit SLO target definitions via `GET /v1/admin/slo`.

Configuration knobs:
- `SENA_INGESTION_QUEUE_BACKEND=memory|redis`
- `SENA_INGESTION_QUEUE_MAX_SIZE=1000`
- `SENA_INGESTION_QUEUE_REDIS_URL=redis://...` (required for `redis` backend)

Load test harness:

```bash
python scripts/load_test.py --url http://127.0.0.1:8000/v1/evaluate --requests 500 --concurrency 50
```


## Experimental and lab assets

Experimental integrations and demo-only assets are not part of the supported product path.

- Experimental API surfaces: generic webhook, Slack interactions, LangChain callback integration.
- Demo packages: Kubernetes admission demo and monitoring demo workflows.
- Investor/fundraising collateral: kept outside the core product narrative.

Use `docs/LABS.md` as the single index for all of the above.

## Evidentiary-grade audit verification

```bash
python -m sena.cli.main audit --audit-path artifacts/audit/audit.jsonl verify-evidence --keyring configs/audit-keyring.json
python -m sena.cli.main audit --audit-path artifacts/audit/audit.jsonl export-evidence-bundle dec_123 --output artifacts/evidence/dec_123.json
python -m sena.cli.main audit --audit-path artifacts/audit/audit.jsonl export-control-mapping --policy-dir policies/active --output artifacts/evidence/control-mapping.json
python -m sena.cli.main audit --audit-path artifacts/audit/audit.jsonl export-evidence-vault --policy-dir policies/active --output artifacts/evidence/evidence-vault.json
python -m sena.cli.main audit --audit-path artifacts/audit/audit.jsonl export-control-package --policy-dir policies/active --control-id SOC2:CC7.2 --output artifacts/evidence/soc2-cc7-2-package.json
```
