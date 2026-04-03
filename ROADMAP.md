# SENA Roadmap: Deterministic Audit Trail for AI Agent Approvals

## Strategic pivot (April 3, 2026)

SENA is pivoting from a broad "policy engine for enterprise workflows" to a focused wedge:

> **Deterministic audit trail for AI agent approvals with cryptographically verifiable, replayable decision traces.**

The near-term product is **not** a generic policy platform and **not** a broad integration marketplace. It is one complete, high-trust approval workflow that proves AI-generated actions can be approved (or blocked) with evidence that can be independently verified.

## Investor-focused milestones (next 4 months)

- **Month 1:** Merkle proof audit API + K8s demo
- **Month 2:** LangChain integration (audit every LLM tool call)
- **Month 3:** SOC2 Type I with audit proof requirements
- **Month 4:** 5 enterprise design partners

## Why this is different (VC narrative)

Most governance tools answer: **"what decision did the engine return?"**
SENA answers: **"can any third party verify exactly how and why that decision happened, and prove it has not been tampered with?"**

### Competitive differentiation

- **OPA and similar policy evaluators** provide policy decisions but do not provide a cryptographically linked approval evidence chain designed for external verification and replay.
- **AI guardrails platforms** focus on model behavior constraints and content/runtime safety, not deterministic approval workflows with audit-chain verification.
- **SENA’s wedge** is the combination of:
  1. deterministic approval evaluation,
  2. hash-linked decision traces,
  3. replayable evidence artifacts,
  4. API-level proof verification for any decision.

If we execute this wedge, SENA becomes the trust layer for AI agents proposing real infrastructure changes.

## Product focus for next 30 days

### One complete MVP workflow (investor demo)

**Target workflow:** AI change request approval for Kubernetes.

1. An LLM agent proposes a Kubernetes change request.
2. SENA receives the request via one production-quality connector.
3. SENA evaluates deterministic policy and returns `APPROVED` / `BLOCKED` / `ESCALATE_FOR_HUMAN_REVIEW`.
4. SENA records a hash-linked decision trace.
5. Verifier endpoint returns Merkle proof for the decision so a third party can validate chain integrity and lineage.

Success criterion for demo: an investor can watch a change request move from AI proposal to verifiable approval artifact in minutes, then independently validate proof data.

## 30-day execution plan (week-by-week)

## Week 1 (Days 1-7): Foundation integrity hardening

### Priority 1 (must-have)

- Enforce robust idempotency-key contracts on approval ingestion paths.
- Add/standardize webhook signature verification where applicable on supported approval entrypoints.
- Fail closed on missing/invalid signature when signature is configured as required.
- Normalize deterministic duplicate-delivery behavior in evidence output.

### Deliverables

- Idempotency + signature verification acceptance tests.
- Deterministic error contracts for signature and duplicate-delivery paths.
- Updated runbook for secure webhook onboarding.

### Milestone 1 (alpha, day 7)

**Verifiable decision trace for ANY approval** with deterministic ingestion guarantees.

### Week 1 success metrics

- 100% of supported approval ingestion endpoints enforce idempotency-key handling.
- 100% of signed webhook paths verify signatures and reject invalid requests.
- Replay of identical payload + policy bundle yields bit-for-bit stable decision evidence.

## Week 2 (Days 8-14): Verifier proof API + K8s path integration

### Priority 2 (must-have)

- Implement `GET/POST /v1/audit/verify/tree` (exact method to finalize in API review) returning:
  - decision hash,
  - Merkle inclusion proof,
  - chain head/anchor metadata,
  - verification status and failure reasons.
- Add deterministic proof schema and CLI verification helper.
- Start single production-quality Kubernetes workflow connector path.

### Deliverables

- `/v1/audit/verify/tree` endpoint with stable schema and tests.
- End-to-end proof verification example for one decision ID.
- K8s connector skeleton integrated with evaluation + audit pipeline.

### Milestone 2 (demo, day 14)

**Kubernetes admission-controller flow + audit verification proof available end-to-end.**

### Week 2 success metrics

- Verifier endpoint produces proofs for 100% of new decisions.
- External verifier script can validate proof without internal DB access.
- Kubernetes demo path runs deterministically in local/staging replay.

## Week 3 (Days 15-21): Production-quality single connector

### Priority 3 (must-have)

- Build **one** connector to production quality (recommended: Kubernetes admission webhook).
- Harden connector for retries, duplicate delivery, timeout budgets, and clear operator errors.
- Ship deterministic fixture pack for the connector’s key failure modes.

### Explicit de-prioritization during this window

- No second first-class connector.
- ServiceNow/Jira remain example integrations, not the GTM centerpiece.

### Week 3 success metrics

- Connector SLA and retry behavior documented and tested.
- p95 decision latency within demo target budget (define and enforce in CI smoke checks).
- Zero nondeterministic test failures across repeated replay runs.

## Week 4 (Days 22-30): Investor demo packaging + partner traction

### Packaging objectives

- Build investor-ready demo script: AI-proposed K8s change → SENA decision → cryptographic proof verification.
- Publish "trust demo" artifacts bundle (request, decision, trace, proof, replay output).
- Prepare design-partner onboarding kit focused on verification endpoint adoption.

### Milestone 3 (traction, day 30)

**Three design partners actively using audit verification endpoint (`/v1/audit/verify` + tree proof endpoint) in pilot workflows.**

### Week 4 success metrics

- 3 design partners complete at least one verified approval flow.
- 1-click demo script executes successfully in staging environment.
- Investor deck includes proof-of-verifiability claims backed by reproducible artifacts.

## Priority stack (in order)

1. **Priority 1 (Week 1-2):** Idempotency keys + webhook signature verification.
2. **Priority 2 (Week 2-3):** `/v1/audit/verify/tree` Merkle proof endpoint.
3. **Priority 3 (Week 3-4):** One production-quality connector (Kubernetes webhook preferred).

## Explicit deferrals (post-traction)

These are important but intentionally deferred until wedge validation:

- Multi-tenancy control plane expansion.
- OIDC/RBAC enterprise identity integration.
- Horizontal scaling and distributed control-plane optimization.
- Policy authoring UI (CLI-first delivery remains the execution path).

## Messaging and positioning updates

Use this language consistently:

- **Primary phrase:** deterministic audit for AI agents.
- **Do not lead with:** "AI-assisted policy engine".
- **Do not position as:** general guardrails platform.
- **Integrations framing:** Kubernetes approval flow is the flagship; Jira/ServiceNow are example integrations.

## Investor-facing proof points to track weekly

- Count of decisions with valid cryptographic proof.
- Mean time to independently verify a decision trace.
- Deterministic replay match rate.
- Number of partner workflows using verification APIs.

If these trend up while failure rates stay flat, SENA demonstrates a defensible trust moat instead of just another policy evaluator.
