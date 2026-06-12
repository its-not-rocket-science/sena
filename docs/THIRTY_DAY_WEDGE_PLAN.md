# 30-Day Wedge Plan: Scope Reduction for Design-Partner Wins

> **Deprecated planning snapshot:** This document is historical context and not the supported product contract. Use `README.md` and `docs/INDEX.md` for current scope.


## One-sentence product definition
Sena is a **change-governance gate for ServiceNow emergency and standard changes** that enforces policy checks and returns a signed approval/deny decision with immutable audit evidence in under 2 seconds.

## Exact use case
- **Moment of truth:** A change request is submitted or moved to approval in ServiceNow.
- **What Sena does:** Evaluate request metadata (service tier, risk level, maintenance window, owner, backout plan) against explicit policy rules and return:
  - decision (`approve`, `deny`, `escalate`)
  - reason codes (human-readable)
  - deterministic evidence payload for audit/review
- **What success looks like in 30 days:**
  - At least 1 design partner routes real (non-production-impacting or shadow) ServiceNow changes through the policy gate.
  - Stakeholders can review decision history and prove why any change was accepted/rejected.

## Target buyer
- **Economic buyer:** Director/VP of Infrastructure Operations or Head of Change Management.
- **Primary champion:** ServiceNow platform owner / ITSM process owner.
- **Primary pain:** CAB delays and inconsistent approvals that create audit risk and operational incidents.

## Required features ONLY (MVP wedge)
1. **ServiceNow inbound webhook + API adapter**
   - Accept change-request payloads and normalize into Sena decision input.
2. **Deterministic policy evaluation**
   - Rule-based checks for required fields, timing windows, risk tier constraints, and ownership controls.
3. **Decision response contract**
   - Return allow/deny/escalate with structured reason codes and remediation hints.
4. **Immutable audit record**
   - Persist request, policy version, decision, timestamp, and actor context in tamper-evident log storage.
5. **Minimal operator visibility**
   - A basic decision log view/filter (CLI or lightweight API endpoint) for partner review sessions.
6. **Design-partner onboarding pack**
   - One reference policy pack + sample ServiceNow mapping + 45-minute activation runbook.

## 30-day execution plan

### Days 1-3: Contract lock + pilot selection
- Lock single workflow: ServiceNow change approval gate only.
- Freeze external surface area (APIs/schemas) for this wedge.
- Confirm one design partner and one success metric set:
  - decision latency
  - false deny/escalate rate
  - audit completeness

### Days 4-10: Build hard path
- Implement/finish ServiceNow adapter for required fields only.
- Implement deterministic evaluator policy set (no AI path in decision loop).
- Ensure signed/immutable audit write per decision.
- Produce golden fixtures for 15-20 real-world change examples.

### Days 11-17: Reliability + usability for partner demos
- Add idempotency and replay-safe processing for duplicate webhooks.
- Add reason-code quality pass (clear, actionable messages).
- Add minimal query endpoint/CLI for decision history by change ID.
- Validate p95 latency and failure handling.

### Days 18-24: Partner pilot dry-runs
- Run shadow mode against partner sample changes.
- Triage top policy mismatches and tune default rules.
- Publish weekly scorecard (approvals/denials/escalations + causes).

### Days 25-30: Production-readiness for wedge
- Finalize onboarding pack and handoff docs.
- Agree go-live guardrails (rollback, escalation path, support SLA).
- Execute live pilot window and collect reference quote + case metrics.

## Features to remove or freeze (explicit)

### Delete from active roadmap now
- **Kubernetes demo** as a first-class go-to-market story.
- **LangChain integration** in primary decisioning path.
- **Jira integration** for initial 30-day delivery.

### Freeze (no net-new build; bug fixes only if already shipped)
- **Simulation UI/workbench** beyond existing core validation tests.
- **Replay tooling** beyond internal debugging utilities.
- **Cross-tool orchestration** (ServiceNow + Jira dual-path workflows).
- **Any “platform” abstractions not required for ServiceNow change gating.**

### Keep only if directly supporting wedge success
- **Policy engine:** keep and narrow to deterministic change-policy checks.
- **Audit chain:** keep and harden because auditability is core buyer value.
- **Simulation/replay:** use internally for QA; not a deliverable surface.

## Non-goals for this 30-day window
- General-purpose governance platform positioning.
- Multi-channel integrations beyond ServiceNow.
- LLM-assisted approvals or natural-language policy authoring.
- Broad dashboarding/BI beyond a minimal decision log.
