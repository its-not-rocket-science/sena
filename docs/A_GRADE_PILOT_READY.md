# A-Grade Pilot-Ready Definition and Gap Assessment

## Scope and intent

This rubric defines an **"A-grade pilot-ready"** bar that is stricter than today's baseline pilot acceptance and intended for design-partner deployments where trust requirements are high.

It is anchored to SENA's supported product path (`src/sena/*`) and supported integrations (Jira + ServiceNow).

## A-grade pilot-ready checklist

Use this checklist as a go/no-go gate. "A-grade" means every item is green.

### 1) Reliability requirements

- [ ] **Deterministic correctness:** replay determinism remains `100%` on curated and production-derived fixtures.
- [ ] **Availability target (pilot window):** API uptime objective documented and measured (target: `>=99.9%` during pilot hours).
- [ ] **Performance SLOs:** p95/p99 evaluate latency and error budget documented per route (`/v1/evaluate`, Jira webhook, ServiceNow webhook).
- [ ] **Concurrency safety:** promotion/evaluation contention behavior proven under load with stable outcomes.
- [ ] **Recovery objective:** RTO/RPO explicitly defined and verified via scheduled restore drills.

### 2) Observability

- [ ] **Golden signals:** request volume, latency, errors, saturation, and queue/backpressure signals exported and dashboarded.
- [ ] **Decision telemetry:** per-outcome, per-policy, and per-integration metrics with stable labels.
- [ ] **Audit health telemetry:** continuous signal for audit verification, chain lag/head hash freshness, archive/restore drill status.
- [ ] **Traceability:** request IDs and correlation IDs are consistently propagated in logs + error payloads.
- [ ] **Operator alerts:** actionable alert rules for SLO burn, audit verification failure, promotion-gate bypass usage.

### 3) Failure handling

- [ ] **Fail-closed by default:** malformed inputs/configurations reject deterministically before side effects.
- [ ] **Stable error contracts:** machine-parseable error codes for all supported failure classes.
- [ ] **Retry/idempotency guarantees:** duplicate delivery and retried promotions remain deterministic across multi-instance deployments.
- [ ] **Degradation policy:** documented behavior under dependency outage (policy store, integration transport, audit sink).
- [ ] **Chaos/fault-injection tests:** top operational failure paths tested (timeouts, storage faults, lock contention).

### 4) Audit durability

- [ ] **Tamper-evident chain:** append-only hash-linked records and verification pass continuously.
- [ ] **Durability beyond single host:** immutable/off-site archival controls defined and validated.
- [ ] **Retention + legal hold:** retention policy, legal hold workflow, and restoration from archive are documented and tested.
- [ ] **Durability SLO:** archive frequency + verification cadence + restore success threshold explicitly tracked.
- [ ] **Evidence portability:** audit evidence can be exported for third-party review without source-code archaeology.

### 5) Integration robustness

- [ ] **Supported integration depth:** Jira + ServiceNow contracts are versioned and fixture-rich for edge cases.
- [ ] **Schema/mapping governance:** mapping changes validated pre-deploy with fail-closed startup checks.
- [ ] **Outbound reliability:** deterministic behavior for connector delivery failures and retries.
- [ ] **Multi-instance idempotency:** idempotency store is durable/shared, not process-local.
- [ ] **Compatibility tests:** contract tests cover payload drift and source-system change scenarios.

### 6) Operational runbooks

- [ ] **Day-2 runbooks complete:** deploy, rollback, key rotation, incident triage, disaster recovery, and audit verification.
- [ ] **Drill cadence defined:** restore and incident drills have owners, schedule, and pass criteria.
- [ ] **Production-check gate enforced:** promotion blocked unless preflight checks pass.
- [ ] **Break-glass governance:** break-glass is auditable, time-bounded, and reviewed.
- [ ] **On-call usability:** runbooks include exact commands, expected outputs, and escalation paths.

## Current repo state vs A-grade bar

Legend: ✅ meets bar, 🟡 partially meets, ❌ gap.

| Area | Status | Evidence from repo |
|---|---|---|
| Deterministic core + replay | ✅ | Deterministic parser/interpreter/evaluator and replay evidence are central acceptance criteria. |
| Startup fail-fast controls | ✅ | Runtime startup validation is explicitly fail-closed with production guardrail checks. |
| Promotion governance gates | 🟡 | Evidence-gated promotions exist, but maturity docs still classify overall system as alpha. |
| Observability baseline | 🟡 | Prometheus counters/histograms and health/readiness endpoints exist, but explicit SLOs/alert playbooks are not formalized. |
| Failure handling coverage | 🟡 | Failure matrix is strong, but explicitly lists not-yet-fully-tested classes (connector outbound delivery failures, lock contention under load). |
| Audit durability | 🟡 | Local JSONL chain provides tamper evidence and archive/restore tools; docs state non-WORM and non-replicated durability. |
| Integration robustness (Jira + SN) | 🟡 | Shared abstraction and runbooks exist, but Jira notes process-local idempotency store for multi-instance deployments. |
| Operational runbooks | 🟡 | Operations, backup/restore, and integration runbooks are substantial, but drill SLAs/owners and alert thresholds are not consistently encoded as gates. |
| Enterprise trust controls | ❌ | Maturity docs call out missing built-in tenancy/OIDC/RBAC admin plane and WORM-native replicated audit storage. |

## Gap analysis

### Reliability gaps

1. No explicit SLO/error-budget contract (availability + latency) tied to pilot go/no-go.
2. Limited demonstrated load/concurrency qualification for promotion + integration paths.
3. RTO/RPO targets are implied by runbooks but not enforced by recurring measured objectives.

### Observability gaps

1. Metrics exist, but no codified alert catalog with thresholds and response windows.
2. No explicit SLO dashboards documented as release gates.
3. Correlation/trace propagation standards are not yet described as hard acceptance criteria.

### Failure handling gaps

1. Failure-mode matrix still marks key production risks as "not yet fully tested".
2. Multi-instance retry/idempotency behavior depends on deployment choices not enforced by default.
3. Fault-injection/chaos style testing is not part of explicit pilot acceptance evidence.

### Audit durability gaps

1. Durability is tamper-evident but not immutable/replicated by default.
2. External immutable retention controls are recommended, not product-enforced.
3. Archive verification cadence/pass targets are not yet hard-gated in CI/deploy flow.

### Integration robustness gaps

1. Supported integrations are strong, but drift/contract-change automation can be deeper.
2. Outbound delivery failure semantics need fuller test coverage.
3. Shared durable idempotency backend is not mandatory in reference deployment profile.

### Operational runbook gaps

1. Runbooks are present, but operator ownership/escalation SLOs are not universally codified.
2. Break-glass governance review loop could be more explicit and automated.
3. Pilot evidence command validates many criteria, but not all A-grade operational criteria.

## Top 5 trust-increasing fixes (prioritized)

1. **Codify and enforce SLOs + error budgets as release gates**  
   Add explicit availability/latency/error-budget targets and fail promotion when breached.

2. **Close durability gap with immutable replicated audit archival pattern**  
   Standardize object-lock + off-site replication profile and verify restore from immutable artifacts weekly.

3. **Harden integration idempotency + outbound failure semantics for multi-instance production**  
   Require durable shared idempotency store and add deterministic retry/poison-path tests for Jira/ServiceNow connectors.

4. **Expand failure-mode testing for currently partial classes**  
   Add targeted tests for connector outbound failures and promotion lock contention to move matrix items to fully tested.

5. **Operationalize alerting + drill governance**  
   Publish alert/runbook matrix with owners, paging thresholds, and required drill cadence tied to pilot acceptance.

## 2–4 week prioritized roadmap

### Week 1: Trust SLO baseline + gates

- Define route-level SLOs (availability, p95, p99, error-rate) for evaluate + Jira + ServiceNow.
- Add SLO evaluation artifact to pilot evidence output and fail `candidate -> active` promotion when out of bounds.
- Deliver an operator-facing alert catalog (metric, threshold, severity, runbook link).

### Week 2: Integration and failure hardening

- Add deterministic tests for:
  - connector outbound transport failures,
  - retry semantics,
  - promotion contention/lock conflicts under concurrency.
- Enforce durable/shared idempotency backend in pilot deployment profile.
- Expand fixture sets for source payload drift and mapping schema edge cases.

### Week 3: Audit durability hardening

- Add immutable archive target profile (object lock / retention policy) to deployment docs.
- Implement recurring archive verification + restore drill command contract with machine-readable results.
- Gate pilot promotion on latest successful drill artifact freshness.

### Week 4: Runbook operationalization and sign-off

- Add single "A-grade pilot readiness" checklist artifact generator combining SLO, durability, failure-mode, and integration checks.
- Define escalation ownership matrix (primary/secondary, response windows).
- Conduct tabletop + live drill, capture evidence bundle, and formalize pilot go/no-go sign-off.

## Exit criteria for this roadmap

At end of 2–4 weeks, trust materially increases when:

- all five top fixes above have machine-verifiable artifacts,
- pilot evidence includes SLO + durability + failure-mode closure metrics,
- remaining non-goals are explicitly acknowledged in the pilot contract.
