# Required-Now Task List (Issue-Ready)

Date: 2026-04-18

Use each section below directly as a GitHub issue body.

## [P0] Disallow allow-all webhook verifiers in pilot/prod

- **Category:** security/authz
- **Problem:** runtime currently falls back to allow-all webhook verifiers when secrets are absent.
- **Implementation anchor:** `src/sena/api/runtime.py` verifier construction for Jira/ServiceNow.

### Scope
- Add startup validation: in `pilot` and `production`, if Jira mapping is enabled then Jira secret(s) are required; same for ServiceNow.
- Keep development-mode fallback only with explicit warning log.
- Add tests for mode-specific behavior.

### Acceptance criteria
- [ ] Pilot startup fails when supported connector mapping is enabled without secret.
- [ ] Production startup behavior remains fail-closed.
- [ ] Development mode allows fallback and emits explicit warning.
- [ ] Regression tests cover Jira + ServiceNow parity.

---

## [P0] Make sensitive-operation step-up cryptographically verifiable

- **Category:** security/authz
- **Problem:** step-up and dual-approval are currently header-presence checks.
- **Implementation anchor:** `src/sena/api/auth.py` (`evaluate_sensitive_operation`).

### Scope
- Add verifiable step-up token format (e.g., signed assertion with actor, time, operation).
- Bind approver identities to authenticated principal/claims; enforce distinct approvers.
- Keep stable API error codes for denial reasons.

### Acceptance criteria
- [ ] Forged headers without valid step-up assertion are rejected.
- [ ] Same approver used twice is rejected.
- [ ] Valid signed step-up assertion with distinct approvers is accepted.
- [ ] Contract tests assert stable denial `error.code` + details keys.

---

## [P0] Replace process-local idempotency lock with storage-atomic claim

- **Category:** correctness
- **Problem:** idempotency lock is in-process and not safe across workers.
- **Implementation anchor:** `src/sena/api/dependencies.py` + `src/sena/api/processing_store.py`.

### Scope
- Introduce atomic idempotency key claim in backing store.
- Remove reliance on in-memory lock map for correctness.
- Preserve existing payload-fingerprint conflict semantics.

### Acceptance criteria
- [ ] Concurrent same-key requests across multiple workers produce one execution path.
- [ ] Duplicate request returns deterministic cached response.
- [ ] Same key + different payload returns deterministic 409 conflict.
- [ ] Connector webhook routes and generic evaluate routes share same behavior.

---

## [P0] Enforce durable ingestion queue in pilot profile

- **Category:** durability/recovery
- **Problem:** default pilot queue path can be memory-backed and lose data on restart.
- **Implementation anchor:** `src/sena/api/config.py`, `src/sena/api/runtime.py`, `src/sena/storage_backends.py`.

### Scope
- Change pilot startup validation to require non-volatile queue backend.
- Add explicit override flag only for local test harnesses (not default pilot).
- Update deployment docs and profile examples.

### Acceptance criteria
- [ ] `SENA_RUNTIME_MODE=pilot` + memory queue without explicit unsafe override fails startup.
- [ ] Durable queue configuration passes startup.
- [ ] Ops docs reflect new pilot requirement and failure message.

---

## [P1] Persist async job metadata and result references across restart

- **Category:** durability/recovery
- **Problem:** async jobs are in-process only and lose state/results on restart.
- **Implementation anchor:** `src/sena/services/async_jobs.py`, job endpoints in API routes.

### Scope
- Add persisted job store abstraction (SQLite acceptable for pilot).
- Persist state transitions (`queued/running/terminal`) and result references.
- Rehydrate active/recent jobs during startup.

### Acceptance criteria
- [ ] Submitted jobs remain queryable after API restart.
- [ ] Terminal state/result contract is stable before and after restart.
- [ ] Timeout/cancel behavior remains deterministic and tested.

---

## [P1] Disable experimental routes by default in pilot/prod

- **Category:** product coherence
- **Problem:** experimental endpoints are still mounted in default runtime.
- **Implementation anchor:** `src/sena/api/app.py`, `src/sena/api/routes/integrations.py`.

### Scope
- Introduce route registration gate by runtime mode and explicit opt-in flag.
- Keep experimental availability in development mode.
- Document route matrix per mode.

### Acceptance criteria
- [ ] Pilot/prod default: experimental webhook/slack routes are not registered.
- [ ] Development default: experimental routes registered and marked with experimental header.
- [ ] New tests assert route availability matrix by mode.

