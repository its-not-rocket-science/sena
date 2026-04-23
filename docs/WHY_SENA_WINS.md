# Where SENA Differentiates (Supported Scope, Alpha Maturity)

## Executive summary (scoped)

SENA’s wedge is **not** “better prompts” or “more AI.” It is operational control over policy decisions that must be replayed, reviewed, promoted, and audited across systems.

Maturity boundary: this document describes relative strengths of the current supported path, not a claim of full enterprise readiness. For canonical maturity posture, defer to `docs/READINESS.md`.

For technical buyers, the durable differentiation is:

1. **Deterministic replay over probabilistic outputs**.
2. **Release-gated policy lifecycle over ad hoc workflow edits**.
3. **Signed bundle provenance over mutable rule folders**.
4. **Tamper-evident audit hash chain over plain logs**.
5. **Cross-system policy portability (Jira + ServiceNow) over duplicated per-tool logic**.
6. **Machine-readable review packages over screenshots and narrative summaries**.
7. **Simulation-based change impact over “deploy and see what breaks.”**

---

## Competitive baseline: what SENA is replacing

### 1) Rules embedded directly in Jira/ServiceNow workflows

**Typical pattern**
- Approval logic is spread across workflow transitions, custom fields, Business Rules, Flow Designer branches, and scripts.
- Control changes are coupled to workflow implementation details per platform.

**What breaks at scale**
- Re-implementing the same control twice (Jira and ServiceNow) creates drift.
- Policy diff/review is hard because logic is distributed across workflow artifacts.
- Replay and root-cause are brittle without stable decision traces.

### 2) Generic policy engines

**Typical pattern**
- Strong evaluator core, but enterprise teams still need to build lifecycle gates, release provenance, audit packaging, and connector normalization around it.

**What breaks at scale**
- “Policy evaluation exists” is not the same as “policy governance is productionized.”
- Missing control-plane workflows delay design-partner credibility.

### 3) Probabilistic, non-replayable LLM guardrail products

**Typical pattern**
- Runtime checks are model-in-the-loop and can vary with model/version/temperature/provider changes.

**What breaks at scale**
- Post-incident replay cannot guarantee identical outcomes.
- Governance reviewers get confidence scores, not deterministic evidence chains.
- Release safety becomes “best effort” instead of gateable.

---

## SENA’s concrete advantages, with repo evidence

## 1) Deterministic replay

**Why this matters**
- Buyers need to prove “same input + same bundle => same outcome” for incidents and audits.

**What SENA has now**
- A deterministic evaluator and precedence model that emits stable decision traces.
- Decision artifacts include `decision_hash`, `input_fingerprint`, matched/evaluated rule IDs, and precedence explanation.

**Repo proof**
- Evaluator and deterministic trace surface: `src/sena/engine/evaluator.py`, `src/sena/core/models.py`.
- Runtime API evaluation endpoints: `POST /v1/evaluate`, `POST /v1/evaluate/batch` in `src/sena/api/app.py`.
- Real artifact with replay identifiers: `examples/design_partner_reference/artifacts/audit/audit.jsonl`.

**Design-partner caveat**
- Determinism claims are strongest for policy evaluation path; integrations still depend on correct source-field mapping quality.

## 2) Release-gated policy lifecycle

**Why this matters**
- Governance teams need controlled promotion (`draft/candidate/active/deprecated`) with explicit validation evidence.

**What SENA has now**
- Lifecycle transitions and promotion validation, including required validation artifact for `active` promotion and guardrails around invalid transitions.
- Register/promote/rollback/history flows in API and CLI.

**Repo proof**
- Lifecycle transition/validation logic: `src/sena/policy/lifecycle.py`.
- API endpoints: `POST /v1/bundle/register`, `POST /v1/bundle/promote`, `POST /v1/bundle/rollback`, `POST /v1/bundle/promotion/validate`, `GET /v1/bundles/history` in `src/sena/api/app.py`.
- Documentation and operator workflows: `docs/POLICY_LIFECYCLE.md`.
- Promotion evidence artifact: `examples/design_partner_reference/artifacts/promotion-validation.json`.

**Design-partner caveat**
- Approval artifact presence is validated, but artifact semantics are not deeply verified by workflow policy yet.

## 3) Signed bundle provenance

**Why this matters**
- Policy changes should be promoted as signed release artifacts, not mutable files with unclear origin.

**What SENA has now**
- Release manifest generation, signing, and verification.
- Strict signature gate option for registration/promotion validation.

**Repo proof**
- Manifest model/sign/verify pipeline: `src/sena/policy/release_signing.py`.
- Registration path enforcing verification behavior: `src/sena/api/app.py` (`register_bundle`, `_verify_bundle_signature`).
- Reference manifest artifact: `examples/design_partner_reference/artifacts/release-manifest.json`.
- Operator doc: `docs/BUNDLE_SIGNING.md`.

**Design-partner caveat**
- Current primitive is HMAC shared keys; enterprise buyers may require asymmetric keys + external KMS/HSM.

## 4) Audit hash chain (tamper-evident)

**Why this matters**
- Buyers need auditable evidence that decision logs were not silently altered.

**What SENA has now**
- Chained audit records with `previous_chain_hash` and `chain_hash`.
- Verification endpoint and CLI-compatible chain verification.
- Segment/manifest support in JSONL sink flow.

**Repo proof**
- Hash chaining + verification: `src/sena/audit/chain.py`.
- API verification endpoint: `GET /v1/audit/verify` in `src/sena/api/app.py`.
- Audit operations docs: `docs/AUDIT_GUARANTEES.md`.
- Chain-bearing artifacts: `examples/design_partner_reference/artifacts/audit/audit.jsonl`, `examples/design_partner_reference/artifacts/audit-chain-verification.json`.

**Design-partner caveat**
- This is tamper-evident local-file evidence, not immutable WORM storage by itself.

## 5) Cross-system policy portability

**Why this matters**
- Enterprise control teams want one policy intent applied consistently across systems.

**What SENA has now**
- Shared normalized approval model.
- Jira and ServiceNow connectors map source payloads into common fields before evaluation.
- Portable policy pack examples target normalized attributes, not source-specific payload paths.

**Repo proof**
- Normalized event + conversion to `ActionProposal`: `src/sena/integrations/approval.py`.
- Jira and ServiceNow webhook surfaces: `POST /v1/integrations/jira/webhook`, `POST /v1/integrations/servicenow/webhook` in `src/sena/api/app.py`.
- Connector docs: `docs/integrations/JIRA.md`, `docs/integrations/SERVICENOW.md`.
- Portable policy artifacts: `src/sena/examples/policy_packs/portable_vendor_approvals/`, `src/sena/examples/integrations/jira_mappings.yaml`, `src/sena/examples/integrations/servicenow_mappings.yaml`.

**Design-partner caveat**
- Portability currently demonstrates strongest depth in Jira + ServiceNow; other connectors are earlier-stage.

## 6) Machine-readable review packages

**Why this matters**
- Audit, risk, and compliance teams need deterministic review packets, not free-form logs.

**What SENA has now**
- Decision review package schema with stable top-level keys for rules, precedence, facts, bundle metadata, and audit identifiers.
- API endpoint to generate review package directly from evaluate payload.

**Repo proof**
- Package builder: `src/sena/engine/review_package.py`.
- Endpoint: `POST /v1/evaluate/review-package` in `src/sena/api/app.py`.
- Review package documentation: `docs/DECISION_REVIEW_PACKAGES.md`.
- Example artifacts: `examples/design_partner_reference/artifacts/review_packages/CHG0091001.json` (and peers).

**Design-partner caveat**
- Packaging is strong at generation time; long-term case-management connectors and retention workflows are still mostly buyer-implemented.

## 7) Simulation-based change impact

**Why this matters**
- Control changes should be assessed pre-release with measurable impact, not only post-incident.

**What SENA has now**
- Bundle comparison on scenario sets with grouped impact summaries by `source_system`, `workflow_stage`, and `risk_category`.
- API + CLI support for simulation-driven release evidence.

**Repo proof**
- Simulation engine and grouped change outputs: `src/sena/engine/simulation.py`.
- Endpoint: `POST /v1/simulation` in `src/sena/api/app.py`.
- Example scenario sets: `src/sena/examples/scenarios/simulation_scenarios.json`, `examples/design_partner_reference/fixtures/simulation_scenarios.json`.
- Example output artifact: `examples/design_partner_reference/artifacts/simulation-report.json`.

**Design-partner caveat**
- Scenario quality determines impact quality; no built-in asynchronous simulation jobs yet for very large scenario libraries.

---

## Where this can outperform alternatives in scoped pilots

| Buyer requirement | Jira/ServiceNow embedded rules | Generic policy engine | Probabilistic guardrail product | SENA position |
|---|---|---|---|---|
| Deterministic replay with forensic identifiers | Usually fragmented | Possible, but often custom-built | Usually weak/non-replayable | Built-in trace + audit identifiers + hash chain |
| Release-gated lifecycle (candidate→active) | Workflow-specific, hard to standardize | Usually not first-class | Rare | First-class lifecycle + promotion validation |
| Signed provenance of policy bundle | Rare | Optional/custom | Rare | Built-in manifest sign/verify + strict gate |
| Cross-system portability | Low (re-implement per platform) | Medium (if connectors exist) | Medium (if model adapters exist) | Strong for Jira + ServiceNow normalized model |
| Review-ready machine artifacts | Limited | Often DIY | Usually narrative/probabilistic | Built-in decision review package schema |
| Pre-release impact simulation | Usually absent | Sometimes custom | Mostly behavioral tests | Built-in simulation endpoint + grouped diffs |

---

## Proof points still missing before stronger enterprise claims

To make these claims design-partner credible in stricter enterprise procurement, the following repo-specific work should land next:

1. **Upgrade signing trust model beyond shared HMAC keys**
   - TODO: Add asymmetric signature support (e.g., Ed25519) in `src/sena/policy/release_signing.py`.
   - TODO: Add key-management integration hooks (KMS/HSM) and rotation policy docs.

2. **Harden audit durability beyond local JSONL**
   - TODO: Add pluggable immutable/WORM-capable sink implementation under `src/sena/audit/`.
   - TODO: Extend `GET /v1/audit/verify` output with retention/replication attestation metadata.

3. **Deepen lifecycle governance semantics**
   - TODO: Enforce machine-checkable validation artifact schemas in promotion requests in `src/sena/api/schemas.py` + `src/sena/api/app.py`.
   - TODO: Add multi-step approval workflow semantics (not just artifact presence) in policy lifecycle flows.

4. **Expand portability evidence beyond two primary systems**
   - TODO: Promote generic webhook and Slack integration paths from experimental to supported with explicit SLO/error contracts in `src/sena/api/app.py` and docs.
   - TODO: Add additional production-shaped connector mappings and fixtures under `src/sena/examples/integrations/` and `tests/`.

5. **Scale simulation operations**
   - TODO: Add asynchronous simulation jobs and persisted reports for large scenario sets.
   - TODO: Add baseline drift detection and regression thresholds in simulation outputs.

6. **Strengthen review-package downstream interoperability**
   - TODO: Add optional signed review-package envelope and checksum fields in `src/sena/engine/review_package.py`.
   - TODO: Add reference exporters for ticketing/GRC ingestion formats.

7. **Close enterprise control-plane gaps already acknowledged in repo docs**
   - TODO: Land stronger tenancy/RBAC/SSO controls on top of current API key role model.
   - TODO: Add policy-authoring UX and operational runbooks for non-engineering compliance operators.

If these items land, SENA’s story shifts from “promising deterministic governance architecture” to “procurement-ready policy control plane with evidence depth.”
