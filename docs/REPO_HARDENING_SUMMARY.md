# Repository Hardening Summary (April 1, 2026)

## Objective

This hardening pass reduced shallow surface area, made support boundaries explicit, and aligned docs/runtime behavior around SENA's strongest differentiated path: deterministic policy enforcement with deep, normalized Jira + ServiceNow integrations.

## What was cut or demoted

### 1) Demoted to experimental surfaces

The following endpoints remain available but are now explicitly marked as **experimental** (evaluation-only):

- `POST /v1/integrations/webhook`
- `POST /v1/integrations/slack/interactions`

Hardening actions:
- Added runtime response header `x-sena-surface-stage: experimental` for both endpoints.
- Updated README and operations/control-plane docs to remove ambiguity about support level.
- Labeled Slack/webhook-centric example docs as experimental.

Why:
- These surfaces are useful for demos and partner discovery, but have weaker operational depth than the Jira/ServiceNow normalized path.

## What was strengthened

### 1) Single supported integration narrative

Supported depth is now consistently documented as:
- Jira normalized approval webhook
- ServiceNow normalized approval webhook

Docs now consistently reinforce that this is the enterprise-ready integration path for current alpha/pilot scope.

### 2) Supported-vs-unsupported boundaries

The following boundaries are now explicit and aligned:
- Supported product path: `src/sena/policy/*`, `src/sena/engine/*`, `src/sena/api/*`, `src/sena/cli/*`
- Legacy path (unsupported): `src/sena/legacy/*`
- Experimental API surfaces: generic webhook + Slack interactions

### 3) Documentation coherence

Aligned README, roadmap, architecture, operations, and control-plane docs so they tell the same story:
- prioritize depth over connector breadth,
- focus on deterministic controls + policy lifecycle,
- emphasize Jira/ServiceNow as core integration depth,
- keep generic webhook/Slack explicitly experimental.

## Capability completeness checklist (supported major capabilities)

### A) Deterministic policy evaluation core
- Tests: evaluator/interpreter/parser/property tests in `tests/`
- Docs: README + architecture + testing strategy
- Examples: packaged policies/scenarios under `src/sena/examples/`
- Error handling: unified API error envelope and code catalog
- Operational guidance: operations/deployment docs

### B) Policy lifecycle + promotion controls
- Tests: lifecycle/simulation/store tests
- Docs: policy lifecycle/schema evolution/persistence docs
- Examples: design partner reference artifacts and scenarios
- Error handling: promotion validation and bundle lifecycle errors
- Operational guidance: release-signing + deployment profiles

### C) Cross-system normalized integrations (supported)
- Tests: Jira + ServiceNow integration and API coverage
- Docs: dedicated runbooks in `docs/integrations/`
- Examples: mapping configs under `src/sena/examples/integrations/`
- Error handling: integration-specific deterministic error codes
- Operational guidance: startup validation + runtime mode constraints

## Net effect

The repository now presents a smaller and sharper product story:
- depth lives in deterministic core + policy lifecycle + Jira/ServiceNow normalization,
- weakly supported surfaces are clearly demoted instead of implied as equal,
- operators and design partners can quickly identify what is production-shaped versus experimental.
