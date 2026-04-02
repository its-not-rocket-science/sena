# SENA Control Plane (Alpha)

SENA’s control plane is an **alpha deterministic governance layer** for AI-assisted enterprise approval workflows.

## Positioning

SENA is a deterministic policy decision system, not a generalized AI safety platform and not a formal verification framework.

## Primary wedge

**One normalized policy model across Jira + ServiceNow approval events**, with deterministic outcomes and evidence-first release workflows.

## Implemented capabilities

1. **Deterministic evaluation core**
   - Strict rule validation and deterministic precedence handling.
   - Explicit outcomes: allow, block, escalate.

2. **Normalized integration depth (supported today)**
   - Jira webhook normalization + evaluation.
   - ServiceNow webhook normalization + evaluation.
   - Shared normalized approval contract enables portable policy bundles.

3. **Release evidence primitives**
   - Bundle diff and promotion validation APIs.
   - Scenario simulation for baseline vs candidate impact.
   - Trace/provenance metadata for every decision.

4. **Auditable decision records**
   - Hash-linked JSONL audit chain.
   - Verification endpoint for tamper detection.

5. **Policy lifecycle controls**
   - Bundle lifecycle states (`draft`, `candidate`, `active`, `deprecated`).
   - Registry/promotion endpoints for explicit state transitions.

## Integration status labels

### Supported (productized depth)
- `POST /v1/integrations/jira/webhook`
- `POST /v1/integrations/servicenow/webhook`

### Experimental (evaluation-only)
- `POST /v1/integrations/webhook`
- `POST /v1/integrations/slack/interactions`

Experimental surfaces are intentionally unstable and may change without backward-compatibility guarantees.

## Current maturity boundary

SENA is **alpha** and should be represented as pilot-prep infrastructure.

Not yet included as built-in platform controls:
- tenant isolation and enterprise identity/RBAC administration,
- replicated/WORM-native audit storage,
- asynchronous long-running simulation orchestration,
- full policy authoring/approval UI.

## Near-term roadmap alignment

1. Harden Jira + ServiceNow workflows and failure-mode coverage.
2. Enforce simulation-backed promotion gates with better evidence packaging.
3. Improve operational durability (persistence + audit recovery drills).
