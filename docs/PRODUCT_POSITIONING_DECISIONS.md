# Product Positioning Decisions

## Why this document exists

This file records the final documentation decisions used to reconcile product story, roadmap, and implementation reality in this repository.

## Final chosen positioning

### Primary wedge

SENA is positioned as an **alpha deterministic policy control plane for AI-assisted enterprise approval workflows**, with **Jira + ServiceNow** as the current productized integration pair.

### Supported integrations (today)

- Jira webhook normalization/evaluation
- ServiceNow webhook normalization/evaluation

### Experimental integrations

- Generic webhook mapping endpoint
- Slack interaction endpoint

These are explicitly labeled evaluation-only and not contractual.

## Decisions made to remove contradictions

1. **Unified “what SENA is / is not” language across README, architecture, and control-plane docs.**
   - Removed/toned down language that implied generalized AI safety platform scope.

2. **Locked integration taxonomy to supported vs experimental.**
   - Jira + ServiceNow are the only supported integration claims.
   - Generic webhook + Slack are experimental everywhere they appear.

3. **Aligned roadmap and maturity language.**
   - Current stage: alpha.
   - Target stage: pilot-ready (with explicit criteria).
   - Removed claims that implied enterprise-complete maturity today.

4. **Constrained roadmap to top 3 priorities.**
   - Integration depth hardening (Jira + ServiceNow).
   - Promotion governance gates with release evidence.
   - Operational trust baseline (persistence, audit recovery, deployment hardening).

5. **Added explicit non-goals.**
   - No connector marketplace expansion before core integration depth is strong.
   - No formal verification claims.
   - No full enterprise control-plane UX/IAM claims in this alpha phase.

## Why this positioning matches repository reality

- The deterministic evaluation and policy lifecycle core are implemented in `src/sena/*`.
- Jira and ServiceNow integration modules and routes are implemented and tested.
- Generic webhook and Slack routes exist but are narrower and best treated as experimental.
- Enterprise-complete platform controls are documented as not yet built-in.

## Canonical document map

- `README.md` — entry positioning and boundaries
- `docs/CONTROL_PLANE.md` — implemented control-plane capabilities
- `docs/ARCHITECTURE.md` — supported architecture and boundaries
- `docs/TECHNICAL_MATURITY_PLAN.md` — alpha→pilot-ready plan
- `ROADMAP.md` — near-term priorities + non-goals
