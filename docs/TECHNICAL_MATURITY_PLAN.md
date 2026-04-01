# SENA Technical Maturity Plan (Alpha → Enterprise-Credible Deterministic Policy Engine)

## Scope and opinionated goal

This plan intentionally prioritizes **depth in deterministic policy evaluation** over breadth. It is the shortest path from current alpha to credible enterprise pilots, centered on these outcomes:

1. one or two killer real integrations,
2. a credible policy lifecycle story,
3. strong testing around failure modes and migrations,
4. durable audit and persistence guarantees,
5. a compelling reason buyers pick SENA over embedding rules in existing workflow/GRC tools.

Non-goals for this phase:
- no policy authoring UI,
- no broad connector marketplace,
- no tenant control plane,
- no speculative AI/LLM policy generation.

---

## 1) Current state assessment (anchored to repository reality)

### What is already strong

- Deterministic evaluation core exists and is separated from legacy path: parser/validation/interpreter/evaluator pipeline in `src/sena/policy/*` and `src/sena/engine/*`. 
- API surface is versioned (`/v1/*`) with explicit error code catalog and request guardrails in `src/sena/api/app.py`, `src/sena/api/errors.py`, and `src/sena/api/schemas.py`.
- Policy lifecycle primitives already exist:
  - lifecycle states and transition validation in `src/sena/policy/lifecycle.py`,
  - bundle registration/promotion endpoints in `src/sena/api/app.py`,
  - SQLite bundle registry in `src/sena/policy/store.py` with migration entrypoint `scripts/migrate_policy_registry.py` and SQL in `scripts/migrations/001_policy_registry.sql`.
- Tamper-evident audit chain exists in `src/sena/audit/chain.py` with JSONL sink in `src/sena/audit/sinks.py` and verification endpoint (`/v1/audit/verify`) in `src/sena/api/app.py`.
- Integration seam exists with deterministic contracts:
  - webhook mapper (`src/sena/integrations/webhook.py`),
  - Slack escalation client (`src/sena/integrations/slack.py`),
  - connector registry (`src/sena/integrations/registry.py`).

### What blocks enterprise credibility today

- Integrations are generic but not yet productized for a named enterprise system (e.g., Stripe risk review or Jira Service Management approval loop).
- Policy lifecycle is mechanically present, but lacks stronger release gates (e.g., mandatory simulation thresholds tied to promotion).
- Persistence and audit guarantees are local-process-friendly but not yet robust under concurrent write/load and backup/restore drills.
- Migration/testing coverage is good on happy paths, thinner on chaos/failure modes (partial writes, malformed registries, replay/idempotency, drift).
- Value narrative versus embedded rules/GRC is not yet encoded into hard artifacts (golden packs + measurable operational outcomes).

---

## 2) Top 10 maturity gaps (prioritized)

1. **No killer integration package** with deterministic mapping + test fixtures + runbook for one high-value workflow.
2. **No second integration proving portability** of SENA’s policy core across systems.
3. **Promotion is not sufficiently gate-driven** (diff + lifecycle checks exist, but no mandatory scenario regression budget for active promotions).
4. **SQLite registry lacks explicit concurrency/locking and disaster-recovery drill tests**.
5. **Audit chain lacks operational durability profile** (rotation, archival format guarantees, verify-at-restore playbook).
6. **Failure-mode test matrix is incomplete** (timeouts, malformed webhook maps, oversized payload behavior across all critical endpoints, promotion failure rollback).
7. **Migration tooling is one-way/minimal** (init schema only; no versioned upgrade/rollback workflow beyond `001_policy_registry.sql`).
8. **Design-partner readiness contract is implicit**; no explicit “good enough” checklist tied to measurable KPIs.
9. **Enterprise pilot acceptance contract is implicit**; no explicit operational SLO + release evidence bundle.
10. **Competitive wedge is under-instrumented**; no benchmark-style artifacts proving deterministic explainability + controlled lifecycle advantage versus embedded rules.

---

## 3) Build vs not-build decisions (hard cuts)

## Build now

- Productize exactly two integrations deeply:
  1) **Stripe payment/risk approval via webhook mapping**,
  2) **Slack escalation + decision callback loop** (already present, needs hardening and end-to-end artifacts).
- Strengthen policy lifecycle release gates using existing simulation/diff/promotion APIs.
- Harden SQLite + audit durability and migration procedures.
- Expand failure-mode and migration tests in current pytest suite.

## Explicitly do not build now

- OIDC/SSO and full enterprise IAM matrix.
- New generic workflow designer UI.
- Additional integrations beyond Stripe + Slack until these two are design-partner quality.
- Distributed control plane/HA orchestration layer.
- Heavy GRC reporting surface.

Reason: these broaden surface area without proving the five target outcomes.

---

## 4) Sequenced roadmap (with dependencies, risks, rollback, exit criteria)

## Phase 0 — Baseline hardening contract (1 week)

**Objective:** lock quality gates before adding more capability.

**Implementation focus (existing artifacts):**
- Add deterministic release checklist document + CI script references anchored to:
  - `pytest`, `ruff check src tests`,
  - bundle validation/test commands in `src/sena/cli/main.py`,
  - API smoke checks for `/v1/evaluate`, `/v1/bundle/promote`, `/v1/audit/verify`.
- Add explicit design-partner and pilot readiness sections to docs (this plan + README pointer).

**Dependencies:** none.

**Risks:** checklist becomes documentation-only and unenforced.

**Rollback:** keep alpha behavior; no runtime behavior change in this phase.

**Exit criteria:**
- Every release PR includes reproducible command output for lint/tests/policy tests.
- Readiness definitions are documented and referenced from README.

---

## Phase 1 — Killer Integration #1: Stripe webhook decisioning (2 weeks)

**Objective:** prove immediate production value on payment approval/risk policy.

**Implementation focus:**
- Expand deterministic mapping pack in `src/sena/examples/integrations/webhook_mappings.yaml` specifically for Stripe event families.
- Add scenario fixtures under `src/sena/examples/scenarios/` for real-like Stripe events.
- Strengthen webhook mapper validation/error semantics in `src/sena/integrations/webhook.py` and related API path in `src/sena/api/app.py`.
- Add/extend tests:
  - `tests/test_api.py` webhook endpoint failure modes,
  - `tests/test_integrations_registry.py` and new webhook mapping edge tests,
  - policy outcomes tied to example payment rules (`src/sena/examples/policies/payments.yaml`).

**Dependencies:** Phase 0 quality gates.

**Risks:** mapping brittleness across payload variants.

**Rollback plan:** version mapping config; if new mapping fails, revert to prior config and keep core evaluator unchanged.

**Exit criteria:**
- ≥15 deterministic Stripe mapping tests (including malformed payload and unknown event).
- End-to-end `POST /v1/integrations/webhook` fixture suite shows stable decisions and trace IDs.
- Example runbook in docs for onboarding a Stripe-like source in <1 day.

---

## Phase 2 — Killer Integration #2: Slack human escalation closure loop (1.5 weeks)

**Objective:** complete enterprise-friendly human-in-the-loop path.

**Implementation focus:**
- Harden Slack outbound + callback semantics in `src/sena/integrations/slack.py` and `/v1/integrations/slack/interactions` handler in `src/sena/api/app.py`.
- Add idempotency/replay guard behavior for interaction callbacks (state-light deterministic approach).
- Expand tests:
  - `tests/test_slack_integration.py`,
  - API interaction tests in `tests/test_api.py` for malformed action payloads and duplicate callbacks.

**Dependencies:** Phase 1 (shared integration reliability patterns).

**Risks:** network dependency and callback replay edge cases.

**Rollback plan:** disable Slack connector via env config while preserving evaluation outcomes.

**Exit criteria:**
- Deterministic callback parsing for approve/reject + explicit failures for unsupported actions.
- Documented retry/idempotency behavior and validated tests.
- End-to-end escalation scenario from evaluation to callback decision artifact.

---

## Phase 3 — Credible policy lifecycle gates (2 weeks)

**Objective:** make promotion process defensible to risk/compliance stakeholders.

**Implementation focus:**
- Extend promotion validation in `src/sena/policy/lifecycle.py` and API promotion endpoints in `src/sena/api/app.py` to require scenario simulation gates before `candidate -> active`.
- Use existing simulation engine (`src/sena/engine/simulation.py`) and scenario sets (`src/sena/examples/scenarios/simulation_scenarios.json`) as policy release evidence.
- Add lifecycle regression tests in `tests/test_lifecycle_and_simulation.py` and endpoint tests in `tests/test_api.py`.

**Dependencies:** Phase 1–2 (integration scenarios feed realistic release tests).

**Risks:** over-strict gates blocking legitimate emergency policy changes.

**Rollback plan:** maintain an explicit break-glass promotion mode requiring annotated reason and producing audit marker.

**Exit criteria:**
- Promotion to active fails without passing simulation gate.
- Bundle diff + scenario-change summary emitted and persisted for each promotion.
- At least one migration-safe design-partner playbook using draft→candidate→active flow.

---

## Phase 4 — Durable persistence + audit guarantees (2 weeks)

**Objective:** move from “works locally” to “operationally trustworthy.”

**Implementation focus:**
- Harden SQLite repository behavior in `src/sena/policy/store.py`:
  - transaction boundaries,
  - deterministic conflict handling,
  - clearer errors on partial state.
- Introduce next migration(s) in `scripts/migrations/` and migration runner improvements in `scripts/migrate_policy_registry.py`.
- Add audit operational controls around `src/sena/audit/chain.py` and `src/sena/audit/sinks.py`:
  - chain verification at startup (optional strict mode),
  - rotation/archival conventions, restore verification command flow.
- Expand tests:
  - `tests/test_policy_store.py` for concurrency/failure cases,
  - `tests/test_audit_chain_and_schema.py` + `tests/test_audit_sinks.py` for corruption/restore paths.

**Dependencies:** Phase 3 (promotion events should be auditable/persisted reliably).

**Risks:** migration errors causing registry downtime.

**Rollback plan:**
- keep backward-compatible schema migrations,
- backup DB before migration,
- fail startup when schema version mismatch is detected.

**Exit criteria:**
- Documented and tested backup/restore + chain-verify workflow.
- Migration suite tested on fresh DB and upgrade path.
- No silent fallback on persistence/audit failures.

---

## Phase 5 — Competitive wedge proof package (1.5 weeks)

**Objective:** make buyer choice obvious versus embedded rules.

**Implementation focus:**
- Create a reproducible “deterministic governance pack” combining:
  - policy bundle,
  - scenario simulation report,
  - promotion evidence,
  - tamper-evident audit verification output,
  - integration runbook (Stripe + Slack).
- Place artifacts in docs/examples and scriptable commands in CLI/API docs.

**Dependencies:** Phases 1–4 complete.

**Risks:** story remains qualitative without metrics.

**Rollback plan:** none needed; documentation + artifact packaging.

**Exit criteria:**
- One command sequence demonstrates full lifecycle from event ingestion to auditable promotion evidence.
- Buyer-facing comparison table (SENA vs embedded rules) backed by concrete artifacts, not claims.

---

## 5) Workstream dependencies summary

- **Integrations first (Phases 1–2)** create realistic events and escalation loops required to validate lifecycle/persistence under load.
- **Lifecycle hardening (Phase 3)** depends on realistic scenario data from integrations.
- **Persistence/audit durability (Phase 4)** should come after lifecycle semantics stabilize, to avoid repeated schema churn.
- **Competitive packaging (Phase 5)** must be last, because it is evidence synthesis from prior phases.

---

## 6) Strong testing strategy (failure modes + migrations)

Use existing test modules as anchors and extend them intentionally:

- **API failure matrix:** `tests/test_api.py`
  - payload limits/timeouts,
  - invalid lifecycle promotion requests,
  - connector config mismatch behavior,
  - strict error-code contract assertions.
- **Lifecycle & simulation:** `tests/test_lifecycle_and_simulation.py`
  - promotion gate enforcement,
  - scenario change-budget checks,
  - break-glass rollback path.
- **Persistence:** `tests/test_policy_store.py`
  - transaction atomicity,
  - active bundle uniqueness invariants,
  - migration upgrade/downgrade safety.
- **Audit durability:** `tests/test_audit_chain_and_schema.py`, `tests/test_audit_sinks.py`
  - tamper detection,
  - truncated/corrupt file behavior,
  - restore-and-verify workflow.
- **Integration determinism:** `tests/test_integrations_registry.py`, `tests/test_slack_integration.py`
  - mapping strictness,
  - callback idempotency,
  - unsupported action hard-fail behavior.

Quality rule: every new maturity feature ships with at least one explicit failure-mode test and one migration/regression test where applicable.

---

## 7) What “good enough for design partners” means

SENA is good enough for design partners when all are true:

1. Two production-relevant flows are runnable end-to-end:
   - Stripe webhook → deterministic decision,
   - ESCALATE → Slack card → callback decision handling.
2. Policy lifecycle operations are reproducible with evidence:
   - register, diff, simulate, validate promotion, promote.
3. Audit and persistence operations survive basic failure drills:
   - tamper detection works,
   - DB backup/restore and migration tested.
4. Teams can operate SENA with docs/runbooks alone (without source-code archaeology).

---

## 8) What “credible enterprise pilot” means

SENA is credible for an enterprise pilot when all are true:

1. **Determinism and explainability:** repeated identical inputs produce identical outcomes/traces in test and staging.
2. **Release governance:** no `active` promotion without simulation-backed checks and recorded diff evidence.
3. **Operational trust:** audit chain verification and persistence migration drills are part of release checklist.
4. **Failure transparency:** API returns stable, machine-parseable error envelope and no implicit fallback.
5. **Buyer value proof:** evidence pack shows lower policy-change risk and better auditability than embedded-rule alternatives.

---

## 9) Final recommended execution order: next 6 PR-sized slices

1. **PR1: Maturity baseline docs + release checklist wiring**
   - Add this plan and cross-links.
   - Add deterministic release checklist doc with required commands.

2. **PR2: Stripe webhook pack hardening**
   - Expand mapping config + fixtures + webhook failure-mode tests.

3. **PR3: Slack escalation loop hardening**
   - Callback idempotency semantics + robust parsing/error tests.

4. **PR4: Promotion gate enforcement via simulation budgets**
   - Candidate→active gate in lifecycle/API + regression tests.

5. **PR5: SQLite migration v2 + persistence failure tests**
   - Migration framework enhancements + atomicity/concurrency coverage.

6. **PR6: Audit durability runbook + corruption/restore tests + evidence bundle**
   - Operational procedures and scripted verification artifacts.

This order is intentionally narrow: it builds hard proof of deterministic value before expanding product surface.
