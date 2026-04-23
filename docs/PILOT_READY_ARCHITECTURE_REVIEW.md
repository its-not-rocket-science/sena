# Pilot-Ready Architecture Review (Alpha → Pilot)

## Scope and objective

This review optimizes SENA for **reliability, determinism, and operability** with **1–3 design partners**.
It intentionally reduces surface area and defers non-critical capabilities.
It is a **target-state architecture review**, not a statement that all changes are already implemented.
For current maturity claims, defer to `docs/READINESS.md` → **"Canonical maturity statement (source of truth)"**.

---

## 1) Before vs after architecture

### Before (current alpha shape)

```text
Clients (API/CLI/Integrations)
  |
FastAPI routes
  |\
  | +--> ProductionProcessingService (primary execution path)
  | +--> EvaluationService (direct usage in some routes)
  | +--> IntegrationService (provider-specific branching)
  |
Runtime/EngineState (settings + connectors + stores + workers + metrics)
  |
Policy Pipeline: parser -> validator -> interpreter -> evaluator
  |
Audit chain + sinks + verification + archive/legal-hold
  |
Policy lifecycle/store/migrations/schema-evolution/disaster-recovery/release-signing
  |
Integrations (Jira, ServiceNow, generic webhook, Slack, LangChain callback)
  |
Optional recovery workers + DLQ retry paths + simulation/replay endpoints
```

### After (pilot-ready target)

```text
Northbound Ports
  - HTTP API (/v1/evaluate, /v1/integrations/jira/webhook, /v1/integrations/servicenow/webhook)
  - CLI (same use-cases as API)

Application Layer (single orchestration service)
  - DecisionService (deterministic evaluate path only)
  - BundleService (load/activate/verify one active bundle)
  - AuditService (append + verify startup integrity)

Domain/Core Engine
  - parser -> validation -> interpreter -> evaluator (pure deterministic core)
  - core models/enums/types

Infrastructure Adapters
  - PolicyBundleRepository (filesystem OR sqlite, one selected per deployment)
  - AuditSink (jsonl for pilot)
  - JiraAdapter, ServiceNowAdapter (strictly inbound mapping + optional outbound status)

Deferred/Disabled in pilot profile
  - generic webhook mapper
  - Slack interaction path
  - LangChain callback integration
  - replay/simulation APIs in runtime
  - advanced lifecycle operations (rollback/disaster-recovery automation from API)
```

---

## 2) Architectural complexity to remove or defer

1. **Multiple execution paths for decisioning**
   - Today, routing can call `processing_service` and also use `EvaluationService` directly.
   - Pilot target: one authoritative decision orchestration path (`DecisionService`).

2. **Runtime object as mutable god-object (`EngineState`)**
   - Holds settings, rules, connectors, stores, workers, metrics, recovery controls.
   - Pilot target: immutable bootstrapped dependencies passed as explicit constructor params.

3. **Integration surface exceeds pilot needs**
   - Jira + ServiceNow are strategic; generic webhook, Slack, and LangChain increase drift and failure modes.
   - Pilot target: keep Jira + ServiceNow only as supported contract.

4. **Heavy policy lifecycle surface exposed at runtime**
   - Register/promote/diff/rollback/disaster-recovery endpoints expand operational risk.
   - Pilot target: runtime should evaluate a single active bundle; lifecycle managed offline/ops-only.

5. **Replay/simulation mixed into live API plane**
   - Useful for governance, but not required for deterministic transaction evaluation in pilot.
   - Pilot target: move to offline tooling (CLI/scripts), not hot path endpoints.

---

## 3) Top 5 risks in current design

1. **Divergent behavior risk from duplicated orchestration paths**
   - Direct and indirect evaluation paths can drift in defaults, audit behavior, and notifications.

2. **Blast radius risk from broad mutable runtime state**
   - Large `EngineState` increases accidental coupling and startup/runtime regression probability.

3. **Operational ambiguity from experimental integrations in same app surface**
   - Experimental paths can appear production-like and absorb support load.

4. **Control-plane and data-plane coupling**
   - Policy lifecycle and migration concerns living in API runtime increases chance of partial deployments.

5. **Overloaded reliability envelope in alpha**
   - DLQ/recovery/simulation/replay/audit/connector concerns in one process complicate incident diagnosis.

---

## 4) What stays vs removed/deferred vs hardened

## Stays (pilot critical)

- Deterministic policy pipeline: parser -> validator -> interpreter -> evaluator.
- Core API evaluation endpoint (`/v1/evaluate`) with idempotency and structured error handling.
- Jira + ServiceNow inbound integrations.
- Audit append + startup verification.
- Basic health, metrics, and minimal DLQ visibility.

## Removed or deferred (pilot profile)

- Generic webhook integration endpoint.
- Slack interaction endpoint and Slack escalation notifications.
- LangChain callback integration package.
- Runtime replay/simulation endpoints (keep as offline CLI-only tooling if needed).
- Runtime rollback/disaster-recovery admin operations.
- Automatic recovery worker in default pilot deployment.

## Must be hardened before pilot

1. **Single decision path invariant**
   - All API and integration flows must call one service (`DecisionService.evaluate(...)`).
2. **Strict API profile gating**
   - Pilot mode must hard-disable deferred routes at startup.
3. **Deterministic defaults centralization**
   - Default decision and strict-require-allow behavior defined in one place only.
4. **Startup fail-fast contract**
   - Missing bundle, invalid signatures (if enabled), and connector misconfig must fail startup explicitly.
5. **Audit durability guarantees**
   - Append failures are explicit, measurable, and never silently ignored.

---

## 5) Revised module boundaries and minimal surface area

```text
sena/core
  - domain models, enums, value objects

sena/policy
  - parsing/validation/interpreter
  - bundle loading + signature verify

sena/engine
  - evaluator + trace generation (pure deterministic)

sena/application   (new logical boundary; can be introduced by moving services/*)
  - decision_service.py     # single orchestration entrypoint
  - integration_service.py  # provider mapping calls decision_service only
  - audit_service.py        # append/verify abstraction
  - bundle_service.py       # runtime bundle selection/activation

sena/adapters
  - api/ (FastAPI routes/controllers only)
  - integrations/ (jira, servicenow adapter implementations)
  - persistence/ (sqlite/fs repositories, processing store)
  - observability/ (metrics/logging)
```

Boundary rules:
- `api/routes/*` may depend on `application/*` and `api/schemas` only.
- `application/*` may depend on `engine|policy|core|adapters` ports, never on route modules.
- `engine|policy|core` remain framework-agnostic and deterministic.
- `integrations/*` must not instantiate evaluator directly.

---

## 6) Concrete refactor plan (file/module level)

### Phase 1 — collapse orchestration to one path

1. Create `src/sena/services/decision_service.py` (or `src/sena/application/decision_service.py`) and move shared evaluate logic from:
   - `src/sena/services/evaluation_service.py`
   - `src/sena/services/production_processing_service.py`
2. Update routes to call decision service only:
   - `src/sena/api/routes/evaluate.py`
   - `src/sena/api/routes/integrations.py`
3. Keep `EvaluationService` as thin compatibility wrapper (temporary) with deprecation note.

### Phase 2 — reduce runtime state coupling

1. Split `EngineState` construction in `src/sena/api/runtime.py` into explicit dependency structs:
   - `RuntimeConfig`
   - `RuntimePorts` (repo/audit/integrations)
   - `RuntimeServices`
2. Remove optional mutable attributes where possible; set once during startup.

### Phase 3 — pilot profile route gating

1. Add startup profile gating in app assembly:
   - `src/sena/api/app.py`
   - `src/sena/api/config.py`
2. In `pilot` mode, do not register deferred routes:
   - disable `/v1/integrations/webhook`
   - disable `/v1/integrations/slack/interactions`
   - disable `/v1/simulation*` and `/v1/replay*`
   - disable lifecycle admin routes not required for partner operations

### Phase 4 — lifecycle control-plane isolation

1. Keep lifecycle modules but remove runtime write operations from default API profile:
   - `src/sena/policy/lifecycle.py`
   - `src/sena/policy/disaster_recovery.py`
   - `src/sena/api/routes/bundles.py`
2. Retain as operator CLI/script workflow only during pilot.

### Phase 5 — hardening and guardrails

1. Add architecture test coverage for pilot boundary rules:
   - extend `tests/test_architecture_import_boundaries.py`
2. Add golden tests for deterministic parity across API vs integration entry points:
   - add/extend in `tests/test_property_and_golden_regressions.py`
3. Add startup profile tests asserting disabled endpoints in pilot mode:
   - `tests/test_api_app_factory.py`

---

## 7) Pilot-ready module map (minimal)

## Tier A: deterministic decisioning (must be productionized)
- `src/sena/policy/*` (parse/validate/interpreter)
- `src/sena/engine/*` (evaluate/trace)
- `src/sena/core/*`
- `src/sena/services/decision_service.py` (target)

## Tier B: required runtime adapters
- `src/sena/api/app.py`, `src/sena/api/runtime.py`, `src/sena/api/routes/evaluate.py`
- `src/sena/api/routes/integrations.py` (Jira + ServiceNow only)
- `src/sena/integrations/jira*.py`, `src/sena/integrations/servicenow*.py`
- `src/sena/audit/*` (append + verify only in pilot)

## Tier C: deferred/disabled for pilot
- `src/sena/integrations/webhook.py`
- `src/sena/integrations/slack.py`
- `src/sena/integrations/langchain/*`
- simulation/replay endpoints and related runtime paths
- advanced lifecycle/admin mutation endpoints

---

## 8) Outcome criteria for pilot readiness

- One deterministic evaluation path across all entry points.
- No experimental endpoints registered in pilot runtime.
- Startup fails fast on any mandatory config/integrity error.
- Audit chain append + verification are observable and deterministic.
- Architecture tests enforce dependency direction and profile boundaries.
