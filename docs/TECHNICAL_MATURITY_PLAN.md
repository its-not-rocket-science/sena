# SENA Technical Maturity Plan (Alpha → Pilot-Ready)

## Positioning lock

This plan aligns to one product story:

- **Primary wedge:** deterministic policy decisioning for AI-assisted approval workflows.
- **Supported integrations:** Jira + ServiceNow.
- **Experimental integrations:** generic webhook + Slack interactions.

## Alpha reality (current)

Implemented now:
- deterministic policy parser/validator/interpreter/evaluator,
- versioned API and CLI surfaces,
- bundle lifecycle primitives (register, diff, validate promotion, promote),
- simulation/replay features,
- hash-linked audit chain verification,
- Jira and ServiceNow normalized integration routes.

Not yet pilot-ready by default:
- enterprise tenancy + OIDC/RBAC admin plane,
- replicated/WORM-native audit durability,
- full asynchronous job orchestration,
- full policy authoring and collaboration UI.

## Top 3 priorities to reach pilot-ready

### 1) Integration depth hardening (Jira + ServiceNow)
- Expand deterministic mapping fixtures and edge-case coverage.
- Strengthen failure contracts for unsupported events, missing required fields, duplicate delivery handling.
- Publish design-partner runbooks that avoid source-code archaeology.

### 2) Promotion governance gates
- Enforce simulation-backed promotion checks for candidate→active.
- Require promotion evidence artifacts (diff + scenario deltas + provenance).
- Support explicit break-glass promotion with auditable reason capture.

### 3) Operational trust baseline
- Improve persistence durability and migration safety.
- Add backup/restore + audit verification drills as repeatable runbooks.
- Tighten deployment hardening and observability guidance.

## Explicit non-goals (this phase)

- Broad connector marketplace expansion before Jira + ServiceNow depth targets are met.
- Repositioning SENA as generalized AI safety software.
- Formal verification guarantees.
- Full enterprise control-plane UX/IAM surface.

## Pilot-ready definition

SENA can be called **pilot-ready** only when all are true:

1. Jira and ServiceNow partner workflows run end-to-end with deterministic outcomes and documented runbooks.
2. Active bundle promotions are evidence-gated by deterministic simulation and diff artifacts.
3. Persistence and audit recovery drills are repeatable and pass in CI-backed checks.
