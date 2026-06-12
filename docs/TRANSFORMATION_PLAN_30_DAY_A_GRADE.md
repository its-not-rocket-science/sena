# A-Grade Pilot Transformation Plan (30 Days)

## Audience and constraints

This plan is for making SENA design-partner pilot ready for the first 3 paying design partners.

Guardrails for this plan:
- no broad net-new features,
- depth over breadth,
- supported path only (`src/sena/*`),
- supported integrations only (Jira + ServiceNow),
- deterministic behavior + audit evidence as non-negotiable core.

## 1) What “A-grade” means

### A. Architecture (A-grade)

An A-grade architecture for this pilot means:

1. **Single, explicit supported path**
   - All critical workflow logic lives in `src/sena/*` with no runtime dependency on legacy modules.
2. **Fail-closed control points**
   - Ingestion, policy loading, promotion, and audit append steps have deterministic reject behavior on invalid/missing prerequisites.
3. **Release-gated policy lifecycle**
   - `candidate -> active` promotion can only happen with simulation + replay + evidence artifacts.
4. **Durability-oriented boundaries**
   - Idempotency, audit persistence, and recovery checks are explicitly modeled as durability boundaries, not convenience behavior.
5. **Operator-first decomposition**
   - Services/routes remain cleanly separated from policy/audit internals so operational checks can be attached without code archaeology.

### B. Reliability (A-grade)

A-grade reliability means:

1. **Determinism SLO**
   - Replay determinism is effectively 100% on regression fixtures.
2. **Pilot uptime objective + latency budget**
   - Explicit API SLOs for evaluate + integration endpoints; breach is visible and actionable.
3. **Multi-instance safety**
   - Duplicate delivery behavior is deterministic with shared durable idempotency guarantees.
4. **Recovery proof, not promises**
   - Backup/restore and audit archive recovery have recurring verified drills with machine-readable output.
5. **Stable failure contracts**
   - Top failure classes return stable, documented error codes and deterministic payloads.

### C. Product clarity (A-grade)

A-grade clarity means:

1. **One sentence product truth**
   - “Deterministic policy decisions for AI-assisted approvals with cryptographically verifiable audit evidence.”
2. **One flagship workflow definition**
   - AI-assisted approval events from Jira/ServiceNow to deterministic outcome + replay + proof.
3. **Clear support boundaries**
   - Supported: Jira + ServiceNow; experimental remains explicitly non-GA.
4. **Onboarding in <1 hour**
   - Design partner can run reference flow + validate proof from docs/scripts alone.
5. **Acceptance contract is executable**
   - Pilot readiness is governed by scriptable gates, not subjective review.

### D. Moat (A-grade)

A-grade moat means:

1. **Deterministic + verifiable together**
   - Decision determinism plus cryptographic audit verification is demonstrated end-to-end.
2. **High switching cost through evidence semantics**
   - Customers embed SENA’s evidence model into compliance/incident workflows.
3. **Integration depth over connector count**
   - Jira/ServiceNow integrations are deeply hardened for edge cases and failure modes.
4. **Operational trust assets**
   - Runbooks, evidence packs, and reproducible validation artifacts become reusable customer trust collateral.
5. **Governance memory**
   - Policy lifecycle history + replay evidence become customer-specific governance knowledge that is hard to replatform.

## 2) Gap inventory (current alpha -> A-grade)

### Architecture gaps

1. **Pilot gates are present but not yet the only path to promotion**; enforcement should be universally mandatory in production profiles.
2. **Durability assumptions remain partly deployment-dependent** (idempotency and archive posture should be mandatory for pilot profile).
3. **A-grade checks are distributed across scripts/docs** and need one canonical “go/no-go” artifact.

### Reliability gaps

1. **SLOs exist conceptually but need hard numeric targets wired into release evidence.**
2. **Concurrency/load qualification is still partial for promotion contention and connector retries.**
3. **Recovery drill cadence/freshness is not yet enforced as a promotion prerequisite.**
4. **Some failure-mode classes are documented as partial and need closure in tests.**

### Product clarity gaps

1. **Message is strong, but onboarding path is still split across many docs.**
2. **Operator playbooks are substantial but not condensed into a single day-0/day-1 pilot handbook.**
3. **Support boundary language is not uniformly mirrored across all externally facing docs.**

### Moat gaps

1. **Proof verification value is implemented, but customer-facing “why this is irreplaceable” packet is not yet packaged as a standard deliverable.**
2. **Evidence portability patterns need stronger first-3-customer templates (audit review, change review, incident replay).**
3. **Benchmark and trust claims need fixed weekly scorecard reporting for partner exec visibility.**

## 3) 30-day execution plan (depth-first)

## Week 1 (Days 1-7): Freeze the pilot contract

### Milestone
A single, executable A-grade contract exists and is required for release.

### Specific code changes

1. `scripts/check_design_partner_ready.py`
   - Add explicit SLO budget input + threshold checks.
   - Add required check: latest successful backup/restore drill age.
   - Add required check: latest successful audit archive verification age.
2. `src/sena/api/metrics.py`
   - Ensure metric names/labels for per-endpoint latency + error-rate are stable and documented.
3. `src/sena/policy/lifecycle.py` + promotion path services
   - Block `candidate -> active` when required evidence artifacts are stale/missing.

### Specific docs to add

1. `docs/PILOT_CONTRACT_A_GRADE.md`
   - Numeric SLOs, error budgets, evidence freshness thresholds.
2. `docs/ALERT_CATALOG.md`
   - Metric -> threshold -> severity -> runbook mapping.
3. `docs/PILOT_OPERATOR_HANDBOOK.md`
   - 60-minute onboarding + first incident flow.

## Week 2 (Days 8-14): Close reliability failure classes

### Milestone
Top reliability risks have deterministic tests and hard gates.

### Specific code changes

1. `src/sena/integrations/jira.py` and `src/sena/integrations/servicenow.py`
   - Harden duplicate-delivery contracts and deterministic retry behavior.
2. `src/sena/api/routes/integrations.py`
   - Normalize machine-readable error codes for signature/idempotency failures.
3. `tests/test_concurrency.py`, `tests/test_idempotency.py`, integration tests
   - Add stress-style deterministic assertions for contention and retried delivery.

### Specific docs to add

1. `docs/ERROR_CONTRACTS.md`
   - Canonical stable error codes and semantic meaning.
2. `docs/INTEGRATION_RELIABILITY_PROFILE.md`
   - Retry/backoff/idempotency behavior and operator expectations.

## Week 3 (Days 15-21): Make durability auditable by default

### Milestone
Durability and recoverability are demonstrated and fresh by policy.

### Specific code changes

1. `scripts/generate_pilot_evidence.py`
   - Include signed timestamps for latest drill artifacts and verification outputs.
2. `src/sena/audit/archive.py` / `src/sena/audit/verification_service.py`
   - Emit machine-readable verification summaries for automation.
3. `scripts/check_design_partner_ready.py`
   - Fail if durability evidence is older than threshold.

### Specific docs to add

1. `docs/AUDIT_DURABILITY_SLO.md`
   - Archive cadence, verification cadence, restore success target.
2. `docs/RECOVERY_DRILL_STANDARD.md`
   - Drill procedure, pass/fail criteria, owner and cadence.

## Week 4 (Days 22-30): Package for first 3 customers

### Milestone
Pilot package is turnkey for onboarding, trust review, and weekly governance.

### Specific code changes

1. `scripts/generate_integration_pilot_pack.py`
   - Output a customer-ready bundle: request, decision, trace, replay, verification summary.
2. `scripts/maturity_scorecard.py`
   - Add weekly pilot KPIs: replay match rate, verification success rate, drill freshness pass rate.
3. `src/sena/examples/*` and partner reference tests
   - Lock fixture set representing first-3-customer use cases.

### Specific docs to add

1. `docs/FIRST_3_CUSTOMERS_PLAYBOOK.md`
   - Onboarding checklist, weekly review template, escalation matrix.
2. `docs/TRUST_REVIEW_PACKET.md`
   - Standard packet for security/compliance/procurement conversations.
3. `docs/PILOT_WEEKLY_BUSINESS_REVIEW.md`
   - KPI definitions, target bands, and remediation mapping.

## 4) Ruthless prioritization (what matters most)

Priority order is strict and should drive staffing and sequencing:

1. **Make A-grade gate executable and mandatory** (no exceptions in pilot profile).
2. **Close deterministic reliability gaps on Jira/ServiceNow ingestion paths.**
3. **Enforce recovery/audit durability freshness as release blockers.**
4. **Standardize stable error contracts for top failure classes.**
5. **Condense operator and customer onboarding into one canonical path.**

Everything else is secondary until these are complete.

## Top 10 changes that matter most

1. Add hard numeric SLO/error-budget checks into design-partner gate script.
2. Block promotion when evidence artifacts are stale or missing.
3. Enforce deterministic duplicate-delivery behavior for Jira + ServiceNow under retries.
4. Publish and enforce stable machine-readable error code taxonomy.
5. Add contention/load tests for promotion + ingestion idempotency paths.
6. Make durability drill freshness a required go/no-go check.
7. Emit machine-readable audit verification summaries for automation.
8. Generate one customer-ready trust packet artifact per release candidate.
9. Create a single pilot operator handbook with copy/paste commands and expected outputs.
10. Track and publish weekly trust KPIs tied to first-3-customer outcomes.

## Definition of done (Day 30)

Pilot is A-grade when:
- all required design-partner checks pass automatically,
- evidence freshness and reliability thresholds are machine-verified,
- first three customers can run and verify the flagship flow with minimal support,
- weekly KPI trend demonstrates stable determinism, verification success, and recovery readiness.
