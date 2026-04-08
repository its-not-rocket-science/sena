# Natural Switching Cost Strategy (No Dark Patterns)

This document outlines how Sena can become difficult to remove **by creating durable, compounding operational value** rather than through coercive patterns.

## Principles

- No dark patterns: no data hostage behavior, punitive contracts, or hidden interoperability limits.
- Customer-value first: each mechanism should reduce risk, lower toil, or improve decision quality.
- Open exits: all critical records should be exportable with integrity metadata.

## 1) Audit Chain as Compliance Source of Record

### Lock-in mechanism
Make Sena's tamper-evident audit chain the canonical evidence stream used for audits, incidents, and regulator requests.

### Why switching cost rises naturally
- Teams rely on continuous, cryptographically linked evidence instead of ad hoc screenshots and ticket comments.
- Recreating historical confidence from another tool is expensive once legal/compliance workflows depend on these proofs.

### Implementation in this repo
- Extend ingestion defaults so every evaluation path emits signed, hash-linked events through the existing chain primitives.
  - `src/sena/audit/chain.py`
  - `src/sena/audit/merkle.py`
  - `src/sena/audit/verification_service.py`
- Add API endpoints for point-in-time audit proof export and verification status.
  - `src/sena/api/routes/bundles.py`
  - `src/sena/api/schemas.py`
- Add operational docs/runbooks for evidence retrieval in legal hold and regulator workflows.
  - `docs/AUDIT_DURABILITY.md`
  - `docs/AUDIT_GUARANTEES.md`

## 2) Policy Bundle Promotion History as Governance Ledger

### Lock-in mechanism
Treat bundle promotion lifecycle (draft -> staged -> production), signatures, and rollback lineage as the official policy governance ledger.

### Why switching cost rises naturally
- Change-management reviews gain full provenance, not just latest policy text.
- Risk and security teams standardize approvals on Sena's promotion evidence artifacts.

### Implementation in this repo
- Persist every promotion decision with approvers, justification, simulation references, and release signature metadata.
  - `src/sena/policy/lifecycle.py`
  - `src/sena/policy/release_signing.py`
  - `src/sena/policy/persistence_models.py`
  - `scripts/migrations/005_promotion_evidence_history.sql`
- Expose immutable promotion timelines and diffable release manifests via API.
  - `src/sena/api/routes/bundles.py`
  - `src/sena/api/routes/evaluate.py`
- Ship a backup/restore contract for this ledger so customers trust durability.
  - `scripts/backup_policy_registry.py`
  - `scripts/restore_policy_registry.py`

## 3) Decision Review Packages Embedded in Human Approval Workflows

### Lock-in mechanism
Make Sena-generated decision review packages the standard artifact attached to Jira/ServiceNow/Slack approval flows.

### Why switching cost rises naturally
- Reviewers save time with consistent rationale, evidence links, and simulation context.
- Institutional process memory accumulates in package references across thousands of tickets.

### Implementation in this repo
- Expand review package payloads with structured "facts used", "controls evaluated", and "counterfactual simulation" sections.
  - `src/sena/engine/review_package.py`
  - `src/sena/engine/explain.py`
  - `src/sena/engine/simulation.py`
- Enforce integration mappings that store package IDs on external tickets.
  - `src/sena/integrations/jira.py`
  - `src/sena/integrations/servicenow.py`
  - `src/sena/integrations/slack.py`
- Provide reference playbooks and mapping examples.
  - `docs/integrations/JIRA.md`
  - `docs/integrations/SERVICENOW.md`
  - `src/sena/examples/integrations/*.yaml`

## 4) Replay + Simulation Baselines as Release Gate

### Lock-in mechanism
Use Sena replay/simulation outputs as mandatory go/no-go checks before policy releases and model/process changes.

### Why switching cost rises naturally
- Teams gain deterministic regression confidence tied to their own historical traffic.
- Rebuilding equivalent replay infrastructure elsewhere is high effort and risky.

### Implementation in this repo
- Promote replay suites and scenario baselines into required checks in CI/release workflows.
  - `src/sena/engine/replay.py`
  - `src/sena/engine/simulation.py`
  - `src/sena/policy/test_runner.py`
- Persist baseline fingerprints and drift thresholds per policy bundle.
  - `src/sena/policy/store.py`
  - `src/sena/policy/persistence_models.py`
- Add docs for "promotion blocked due to simulation drift" with explicit remediation steps.
  - `docs/POLICY_LIFECYCLE.md`
  - `docs/PERFORMANCE.md`

## 5) Integration-normalized Approval Graph as Operational Backbone

### Lock-in mechanism
Make Sena's normalized approval model the central router for multi-system approvals (Jira, ServiceNow, webhooks, future systems).

### Why switching cost rises naturally
- New systems can plug into one canonical decision graph instead of bespoke per-tool logic.
- Operations teams standardize controls once and project them to multiple execution surfaces.

### Implementation in this repo
- Harden the internal normalized schema and mapping compiler with explicit versioning and migration tools.
  - `src/sena/integrations/approval.py`
  - `src/sena/integrations/registry.py`
  - `src/sena/policy/schema_evolution.py`
  - `scripts/migrate_policy_registry.py`
- Publish stable APIs for mapping validation, dry-run routing, and compatibility checks.
  - `src/sena/api/routes/integrations.py`
  - `src/sena/api/schemas.py`
- Provide import/export of mapping packs as portable artifacts (zip or signed bundle).
  - `src/sena/services/integration_service.py`
  - `src/sena/services/bundle_service.py`

## APIs and Artifacts to Make System-of-Record

To maximize legitimate stickiness, prioritize these durable interfaces:

- **Audit Evidence API**: query by decision ID, date range, legal hold tag, and proof verification status.
- **Promotion Ledger API**: complete release lineage, signatures, approvals, and rollback ancestry.
- **Review Package Artifact**: immutable JSON + human-readable summary attached to every approval ticket.
- **Replay Baseline Artifact**: signed regression reports with scenario coverage and drift metrics.
- **Integration Mapping Pack**: versioned mapping spec, validation report, and migration manifest.

Each should support:
1. Stable schema versions.
2. Export with integrity checks.
3. Backward-compatible readers.
4. Explicit deprecation windows.

This keeps migration *possible* while making Sena hard to replace because it is deeply useful and operationally central.
