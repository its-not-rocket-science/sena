# Canonical Workflow: Change-Approval Decision with Deterministic Evidence

## Why this is the canonical workflow

This workflow is the highest-value wedge in the current product scope:

- **Business value:** governs high-risk change approvals in Jira + ServiceNow.
- **Determinism + audit:** every approval decision is replayable and cryptographically verifiable.
- **Fast proof:** one script generates promotion, evaluation, replay, and audit evidence.

---

## Step-by-step flow (user + system)

### Step 1 — Operator runs the integration pack

**User action**

```bash
PYTHONPATH=src python examples/design_partner_reference/run_reference.py
```

**System input**

- Candidate and active bundles:
  - `examples/design_partner_reference/policy_bundles/candidate/*`
  - `examples/design_partner_reference/policy_bundles/active/*`
- Integration mappings:
  - `examples/design_partner_reference/integration/servicenow_mapping.yaml`
  - `examples/design_partner_reference/integration/jira_mapping.yaml`
- Reference fixtures and scenarios from `examples/design_partner_reference/fixtures/*`.

**System output**

- End-to-end artifacts under `examples/design_partner_reference/artifacts/*`.

**Evidence generated**

- `simulation-report.json`
- `promotion-validation.json`
- `evaluation-results.json`
- `normalized-event-examples.json`
- `replay-report-stable.json`
- `replay-report-policy-update.json`
- `audit-chain-verification.json`
- `review_packages/*.json`

**What user cares about**

- "Did the system execute the full deterministic governance flow and produce evidence artifacts I can inspect?"

---

### Step 2 — Candidate bundle promotion gate is evaluated

**User action**

- Reviews promotion gate summary (via `demo_15m.sh` or JSON artifact inspection).

**System input**

- Candidate vs active bundle diff.
- Simulation scenarios.
- Release signature validation data.

**System output**

- `promotion-validation.json` with:
  - promotion gate validity,
  - signature verification validity.

**Evidence generated**

- A machine-readable promotion decision with deterministic gate results and signing status.

**What user cares about**

- "Can this policy change be safely promoted with explicit, fail-closed evidence?"

---

### Step 3 — Incoming approval events are normalized and evaluated

**User action**

- Sends Jira/ServiceNow approval events (in demo: fixture-backed runs).

**System input (exact contract shape)**

- Event payload + source mapping.
- Active bundle + deterministic evaluator.

**System output (exact outcome contract)**

- One of:
  - `APPROVED`
  - `BLOCKED`
  - `ESCALATE_FOR_HUMAN_REVIEW`
- Trace/provenance references and review package content.

**Evidence generated**

- `evaluation-results.json`
- `normalized-event-examples.json`
- `review_packages/*.json`

**What user cares about**

- "Is the decision consistent across systems and explainable for auditors and operators?"

---

### Step 4 — Deterministic replay and drift checks run

**User action**

- Reviews replay reports.

**System input**

- Previously evaluated decisions/events.
- Baseline policy vs updated policy for drift analysis.

**System output**

- `replay-report-stable.json` (expected no outcome drift for same inputs/policy).
- `replay-report-policy-update.json` (explicitly surfaces policy-induced outcome drift).
- `sena replay export-canonical` output (canonical replay artifact for external verification).

**Evidence generated**

- Determinism proof and policy drift delta report.
- Canonical replay artifact containing stable hashes/provenance and replay-safe payload only.

**Stability boundary**

- `canonical_replay_payload` is replay-stable and intended for equality checks.
- Full response payloads are **not** guaranteed stable across runs because operational fields
  (for example `decision_id`, timestamps, chain/write metadata) are intentionally volatile.

**What user cares about**

- "Can I prove that repeated runs are stable, and isolate only intended changes?"

---

### Step 5 — Audit chain verification completes

**User action**

- Verifies the audit output (artifact and/or API verification endpoints).

**System input**

- Hash-linked JSONL audit records and Merkle verification logic.

**System output**

- `audit-chain-verification.json` asserting chain validity.

**Evidence generated**

- Tamper-evident verification artifact suitable for compliance handoff.

**What user cares about**

- "Can we prove records are complete and untampered after the fact?"

---

## Exact inputs/outputs summary

| Stage | Inputs | Outputs |
|---|---|---|
| Promotion gate | Candidate bundle, active bundle, simulation scenarios, signatures | Promotion valid/invalid + signature valid/invalid |
| Decision evaluation | Normalized Jira/ServiceNow event + active bundle | `APPROVED` / `BLOCKED` / `ESCALATE_FOR_HUMAN_REVIEW` + trace/review package |
| Replay/drift | Stored decisions/events + baseline/updated policy | Stable replay diff + policy-update drift report |
| Audit verification | Hash-linked audit stream | Chain verification status + proof details |

---

## Map to current repository

### User-facing demo and runbook

- Demo entrypoint: `examples/design_partner_reference/demo_15m.sh`
- Pack orchestration: `examples/design_partner_reference/run_reference.py`
- Pack docs: `examples/design_partner_reference/README.md`
- Operator guidance: `examples/design_partner_reference/operator_runbook.md`

### Core product paths implementing this flow

- Policy lifecycle + validation + signing:
  - `src/sena/policy/lifecycle.py`
  - `src/sena/policy/validation.py`
  - `src/sena/policy/release_signing.py`
- Deterministic evaluation + replay + review packages:
  - `src/sena/engine/evaluator.py`
  - `src/sena/engine/replay.py`
  - `src/sena/engine/review_package.py`
- Audit chain + verification:
  - `src/sena/audit/chain.py`
  - `src/sena/audit/merkle.py`
  - `src/sena/audit/verification_service.py`
- Supported integration depth:
  - `src/sena/integrations/jira.py`
  - `src/sena/integrations/servicenow.py`
- API surfaces:
  - `src/sena/api/routes/evaluate.py`
  - `src/sena/api/routes/integrations.py`
  - `src/sena/api/routes/bundles.py`

### Existing verification coverage

- Workflow tests include:
  - `tests/test_flagship_workflows.py`
  - `tests/test_decision_review_package.py`
  - `tests/test_replay_drift.py`
  - `tests/test_audit_merkle.py`
  - `tests/test_bundle_release_signing.py`

---

## Production hardening gaps

1. **Single command, single pass/fail gate**
   - Add `make canonical-workflow-check` to enforce required artifacts and invariants in CI.

2. **Evidence schema checks at the boundary**
   - Enforce strict JSON Schema validation for canonical evidence files to prevent downstream drift.

3. **Fail-closed policy promotion defaults in production config**
   - Production deployment profiles should mandate promotion and signing gates by default.

4. **Operational SLOs per workflow step**
   - Publish target latency, verification completion time, and replay throughput for pilots and on-call operations.

5. **Dedicated canonical-workflow dashboard panel set**
   - Add focused panels for promotion gate health, decision outcomes, replay drift counts, and audit verification freshness.
