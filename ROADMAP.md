# SENA Roadmap (Alpha → Pilot-Ready)

## Product narrative anchor

SENA’s primary wedge is **deterministic policy decisioning for AI-assisted approval workflows, with Jira + ServiceNow as the supported integration pair**.

## Current state (April 2, 2026)

- Stage: **Alpha**
- Supported integrations: Jira + ServiceNow
- Experimental integrations: generic webhook + Slack interactions
- Focus: deterministic evaluation, release evidence, and normalized cross-system policy portability

## Top 3 roadmap priorities

### 1) Productize Jira + ServiceNow depth
- Expand fixture packs and mapping validation for realistic partner workflows.
- Improve failure-mode coverage for unsupported events, missing required fields, and duplicate deliveries.
- Publish tighter design-partner runbooks for onboarding and operations.

### 2) Make policy promotion governance enforceable
- Require simulation-backed gates for candidate→active promotion.
- Standardize promotion evidence artifacts (diff, simulation deltas, provenance).
- Add explicit break-glass behavior with auditable annotations.

### 3) Reach pilot-ready operational baseline
- Harden persistence and migration reliability for bundle lifecycle state.
- Add repeatable audit-chain recovery and verification drills.
- Improve deployment/observability guidance for controlled pilot environments.

## Explicit non-goals (this phase)

- Building a broad connector marketplace before Jira + ServiceNow depth goals are met.
- Positioning SENA as a generalized AI safety platform.
- Claiming formal verification guarantees.
- Shipping a full enterprise control plane (multi-tenant OIDC/RBAC admin UX) in this alpha cycle.

## Exit criteria to call SENA “pilot-ready”

- 2–3 design-partner workflows on Jira/ServiceNow are repeatable with documented runbooks.
- Promotions to active policy bundles are gated by deterministic evidence.
- Operational recovery drills (audit verification + persistence restore) pass in CI and docs runbooks.
