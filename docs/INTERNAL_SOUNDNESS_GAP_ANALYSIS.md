# Internal Soundness Roadmap (Alpha → Internally Sound)

Date: 2026-04-23

Scope: supported SENA path only (`src/sena/*` with Jira + ServiceNow connectors and supported `/v1/*` API routes).

This document is intentionally implementation-backed: every gap below is tied to current code and/or current readiness docs, with no market-language items.

## Baseline (what is actually implemented now)

Current implementation is consistent with an alpha, narrow, deterministic control-plane core:

- Deterministic evaluation + replay contract and hash-linked audit evidence are implemented in the supported path (`README.md`, `docs/READINESS.md`).
- Supported integration depth is Jira + ServiceNow; generic webhook and Slack remain explicitly experimental (`README.md`, `src/sena/api/routes/integrations.py`).
- Startup fail-fast checks for production controls are implemented (`src/sena/api/runtime.py`).
- Runtime still includes concessions and partial hardening areas that can weaken internal soundness if left unaddressed (details below).

## Gap analysis (implementation-backed)

## 1) Webhook verifier behavior is mode-dependent (resolved for pilot/production, still dev-risk)
- **Classification:** security/authz
- **Evidence in code/docs:**
  - Runtime builds `AllowAllJiraWebhookVerifier` / `AllowAllServiceNowWebhookVerifier` when no shared secret is configured. (`src/sena/api/runtime.py`)
  - RC doc states allow-all verifier remains intentionally available for non-production bootstrap/dev. (`docs/SUPPORTED_PATH_RC_READINESS_2026-04-12.md`)
- **Current status (2026-04-23):** **Resolved for pilot/production**. Startup now fails in `pilot` and `production` when enabled supported connectors are missing webhook secrets; allow-all remains development-only.
- **Why it matters:** development environments can still accept forged inbound events if operators run with missing secrets and assume production-like posture.
- **Good enough before external validation:** keep current pilot/production fail-fast behavior and make development-mode risk explicit in operational docs/checklists.
- **Acceptance tests:**
  1. `SENA_RUNTIME_MODE=pilot` + Jira mapping + no Jira secret → startup fails with deterministic error.
  2. `SENA_RUNTIME_MODE=development` + no secret → explicit warning + startup allowed.
  3. Existing production-fail tests remain green.
- **Required now vs later:** **Later** (already addressed for pilot/production).

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

## 5) Async jobs execute in-process (partial durability, limited orchestration resilience)
- **Classification:** durability/recovery
- **Evidence in code/docs:**
  - `InProcessJobManager` remains explicitly in-process for execution, but persists metadata and result payloads to sqlite and reloads/reconciles jobs on startup. (`src/sena/services/async_jobs.py`)
  - Readiness doc still states robust built-in async orchestration is not complete. (`docs/READINESS.md`)
- **Why it matters:** metadata durability improved, but worker execution remains process-local and not equivalent to distributed job orchestration.
- **Good enough before external validation:** retain current sqlite-backed recovery semantics and avoid implying enterprise-grade async orchestration.
- **Acceptance tests:**
  1. Submit long-running job, restart API, query job status: terminal/recoverable state remains available.
  2. Job cancellation and timeout semantics remain deterministic after restart.
- **Required now vs later:** **Later** (for broader production posture; pilot can remain bounded).

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

## 7) Experimental endpoints are mode-gated (resolved default in pilot/production)
- **Classification:** product coherence
- **Evidence in code/docs:**
  - Experimental integration routes exist, but app route registration now defaults to enabled only in `development`; `pilot`/`production` default to disabled unless explicit override is set. (`src/sena/api/app.py`, `src/sena/api/config.py`)
  - Route handlers still tag surface stage for clarity when enabled. (`src/sena/api/routes/integrations.py`)
- **Current status (2026-04-23):** **Resolved as a default safety control** for pilot/production.
- **Why it matters:** explicit override can still re-enable experimental routes, so operator intent must remain deliberate and documented.
- **Good enough before external validation:** keep default-off posture outside development and treat overrides as explicit risk acceptance.
- **Acceptance tests:**
  1. Pilot profile returns 404/410 for experimental routes by default.
  2. Development profile still exposes experimental routes with explicit stage header.
- **Required now vs later:** **Later** (default posture is already in place).

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
1. Replace header-only step-up/dual-approval checks with verifiable assertions.
2. Make idempotency enforcement storage-atomic across workers.
3. Require durable ingestion queue in pilot profile.

### Later (after internal soundness, before broad production claims)
1. Harden tenant isolation model beyond single-tenant pilot constraints.
2. Add signed downstream audit shipping/verification envelope.
3. Strengthen async orchestration beyond in-process workers for larger jobs.
4. Continue reducing development-mode security footguns (for example allow-all verifier usage).
