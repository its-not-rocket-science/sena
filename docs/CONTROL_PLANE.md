# SENA Control Plane (Alpha)

## Supported product (current scope)

SENA is an **alpha control-plane core for Jira + ServiceNow approval decisioning**.

The supported path is concrete and implemented: ingest Jira/ServiceNow approval events, normalize them into one policy context, evaluate deterministically against versioned bundles, and return machine-actionable outcomes with replayable evidence.

- Outcomes: `APPROVED`, `BLOCKED`, `ESCALATE_FOR_HUMAN_REVIEW`
- Same policy semantics across Jira and ServiceNow
- Deterministic replay artifacts + hash-linked audit verification

Broader connector applicability exists, but it is not the primary supported product claim in this phase.

## Implemented capabilities

1. Deterministic policy evaluation core.
2. Jira + ServiceNow normalized integration routes.
3. Bundle diff, simulation, and promotion-validation release evidence primitives.
4. Hash-linked audit records with verification endpoints.
5. Policy lifecycle state transitions.

## Honest maturity statement

SENA is **alpha**. It should be represented as pilot-prep infrastructure, not as a complete enterprise control plane.

Not yet complete as built-in platform controls:
- full enterprise tenancy administration,
- full OIDC/RBAC admin UX,
- replicated/WORM-native audit storage,
- async long-running orchestration for large simulation workloads,
- full policy authoring/collaboration UI.

## Non-goals (current phase)

- Broad connector marketplace expansion before Jira + ServiceNow depth hardening.
- Generalized AI safety positioning as the primary product narrative.
- Formal verification claims.

## Strategy conflict marker

Any materials framing Kubernetes or other demo connectors as the primary product wedge should be treated as outdated for the current phase.
