# Internal Soundness Roadmap (Alpha → Internally Sound)

Date: 2026-04-18

Scope: supported SENA path only (`src/sena/*` with Jira + ServiceNow connectors and supported `/v1/*` API routes).

This document is intentionally implementation-backed: every gap below is tied to current code and/or current readiness docs, with no market-language items.

## Baseline (what is actually implemented now)

Current implementation is consistent with an alpha, narrow, deterministic control-plane core:

- Deterministic evaluation + replay contract and hash-linked audit evidence are implemented in the supported path (`README.md`, `docs/READINESS.md`).
- Supported integration depth is Jira + ServiceNow; generic webhook and Slack remain explicitly experimental (`README.md`, `src/sena/api/routes/integrations.py`).
- Startup fail-fast checks for production controls are implemented (`src/sena/api/runtime.py`).
- Runtime still includes pilot/development concessions that weaken internal soundness if left unaddressed (details below).

## Gap analysis (implementation-backed)

## 1) Unauthenticated webhook verifier is still possible outside production
- **Classification:** security/authz
- **Evidence in code/docs:**
  - Runtime builds `AllowAllJiraWebhookVerifier` / `AllowAllServiceNowWebhookVerifier` when no shared secret is configured. (`src/sena/api/runtime.py`)
  - RC doc states allow-all verifier remains intentionally available for non-production bootstrap/dev. (`docs/SUPPORTED_PATH_RC_READINESS_2026-04-12.md`)
- **Why it matters:** a pilot or pre-pilot environment can accidentally accept forged inbound events if secrets are omitted.
- **Good enough before external validation:** in `pilot` and `production` runtime modes, startup fails if any enabled supported connector has no webhook verifier secret.
- **Acceptance tests:**
  1. `SENA_RUNTIME_MODE=pilot` + Jira mapping + no Jira secret → startup fails with deterministic error.
  2. `SENA_RUNTIME_MODE=development` + no secret → explicit warning + startup allowed.
  3. Existing production-fail tests remain green.
- **Required now vs later:** **Required now**.

## 2) Step-up / dual-approval controls are header-presence checks, not verified factors
- **Classification:** security/authz
- **Evidence in code/docs:**
  - Sensitive-operation gating checks only for header presence/format (`x-step-up-auth`, approver headers). (`src/sena/api/auth.py`)
- **Why it matters:** a caller with any valid credential can self-assert step-up and approver headers, weakening separation-of-duties controls.
- **Good enough before external validation:** cryptographically verifiable step-up assertion and distinct approver identity checks bound to authenticated principal claims.
- **Acceptance tests:**
  1. Promotion request with forged headers and no valid step-up token → denied.
  2. Promotion with same principal as both approvers → denied.
  3. Promotion with valid step-up token + two distinct mapped approvers → allowed.
- **Required now vs later:** **Required now**.

## 3) Idempotency lock is process-local; cross-instance duplicate writes are possible
- **Classification:** correctness
- **Evidence in code/docs:**
  - Idempotency mutex is in-memory `threading.Lock` map. (`src/sena/api/dependencies.py`)
  - Runtime state store is SQLite-backed, but lock coordination is not distributed. (`src/sena/api/processing_store.py`)
- **Why it matters:** in multi-process or multi-replica deployment, same idempotency key can race and execute duplicate side effects.
- **Good enough before external validation:** idempotency enforcement uses storage-backed atomic semantics (single INSERT/claim pattern) without in-memory lock dependence.
- **Acceptance tests:**
  1. Concurrent duplicate-key requests from two app workers produce one processed response + one replayed cached response.
  2. Payload mismatch with same key returns deterministic 409 conflict across workers.
- **Required now vs later:** **Required now**.

## 4) Ingestion queue defaults to in-memory even in pilot profile
- **Classification:** durability/recovery
- **Evidence in code/docs:**
  - `ApiSettings.ingestion_queue_backend` default is `memory`. (`src/sena/api/config.py`)
  - Storage capability matrix marks memory queue as volatile (lost on restart) and pilot-suitable today. (`src/sena/storage_backends.py`)
- **Why it matters:** accepted inbound events can be lost during process crash/restart.
- **Good enough before external validation:** pilot profile defaults to durable queue backend (Redis or equivalent) with explicit failure if unavailable.
- **Acceptance tests:**
  1. Pilot mode without durable queue config fails startup.
  2. Crash/restart drill with queued-but-unprocessed events shows no event loss.
- **Required now vs later:** **Required now**.

## 5) Async jobs are in-process only; no recovery of job state/results after restart
- **Classification:** durability/recovery
- **Evidence in code/docs:**
  - `InProcessJobManager` is explicitly in-process and stores results in memory (`memory://jobs/...`). (`src/sena/services/async_jobs.py`)
  - Readiness doc says robust built-in async orchestration is not complete. (`docs/READINESS.md`)
- **Why it matters:** simulation/replay jobs appear operational but are non-durable; operators can lose long-running evidence generation state.
- **Good enough before external validation:** persisted job metadata/result references with restart recovery and explicit terminal status semantics.
- **Acceptance tests:**
  1. Submit long-running job, restart API, query job status: terminal/recoverable state remains available.
  2. Job cancellation and timeout semantics remain deterministic after restart.
- **Required now vs later:** **Required now** (for internal soundness of async surfaces).

## 6) Tenant context is data-carried, not hard-isolated by authenticated principal
- **Classification:** safety
- **Evidence in code/docs:**
  - Tenancy context object exists in governance utilities, but enforcement is payload-centric/redaction-centric, not hard multi-tenant guardrail at API boundary. (`src/sena/api/data_governance.py`, `src/sena/api/middleware.py`)
  - Readiness doc states hard multi-tenant isolation is not yet production-grade. (`docs/READINESS.md`)
- **Why it matters:** cross-tenant data handling mistakes can slip through if deployment expands beyond tightly controlled single-tenant usage.
- **Good enough before external validation:** explicit pilot contract enforces single-tenant mode (hard setting + startup guard), or authenticated tenant binding on every request.
- **Acceptance tests:**
  1. Startup fails when multi-tenant mode requested without tenant-bound auth enforcement.
  2. Cross-tenant request (token tenant != payload tenant) is denied.
- **Required now vs later:** **Later** if pilot remains strict single-tenant; **Required now** if multi-tenant pilot is planned.

## 7) Experimental endpoints are registered in the same runtime by default
- **Classification:** product coherence
- **Evidence in code/docs:**
  - Generic webhook and Slack routes are still mounted and tagged via response header as experimental. (`src/sena/api/routes/integrations.py`)
  - Readiness docs position these as outside supported commitment. (`README.md`, `docs/READINESS.md`)
- **Why it matters:** operator confusion and accidental usage of non-supported surfaces in environments assumed to be supported-only.
- **Good enough before external validation:** pilot/production route gating that disables experimental endpoints unless explicit opt-in flag is set.
- **Acceptance tests:**
  1. Pilot profile returns 404/410 for experimental routes by default.
  2. Development profile still exposes experimental routes with explicit stage header.
- **Required now vs later:** **Required now** (coherence + operational safety).

## 8) Audit shipping is best-effort and unsigned
- **Classification:** durability/recovery
- **Evidence in code/docs:**
  - Audit shipper uses retry queue but sends plain JSON payloads (file/http) without signature envelope. (`src/sena/audit/shipper.py`)
  - Readiness docs already say compliance envelope is incomplete. (`docs/READINESS.md`)
- **Why it matters:** downstream archive ingestion integrity/attribution is weaker than source chain guarantees.
- **Good enough before external validation:** optional signed shipper envelope with receiver verification contract; hard-fail option for failed shipment verification.
- **Acceptance tests:**
  1. Signed payload accepted by verifier endpoint.
  2. Tampered shipped payload rejected and quarantined.
- **Required now vs later:** **Later** (valuable but not blocking internal soundness for controlled pilot).

## Prioritization summary

### Required now (to reach internally sound)
1. Enforce webhook secret requirement in pilot/prod (remove allow-all verifier path there).
2. Replace header-only step-up/dual-approval checks with verifiable assertions.
3. Make idempotency enforcement storage-atomic across workers.
4. Require durable ingestion queue in pilot profile.
5. Persist async job state/results across restart.
6. Gate experimental endpoints out of pilot/prod by default.

### Later (after internal soundness, before broad production claims)
1. Harden tenant isolation model beyond single-tenant pilot constraints.
2. Add signed downstream audit shipping/verification envelope.
