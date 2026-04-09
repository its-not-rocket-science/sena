# SENA Control Plane (Alpha)

## Coherent product narrative

- **Primary wedge:** one normalized policy decision layer for Jira + ServiceNow approval events.
- **Supported integration story:** one policy bundle can be evaluated consistently across Jira and ServiceNow with deterministic outcomes (`APPROVED`, `BLOCKED`, `ESCALATE_FOR_HUMAN_REVIEW`) and audit evidence.
- **Experimental bucket:** generic webhook, Slack interactions, LangChain callback, and Kubernetes demo surfaces are evaluation-only.

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
- Generalized AI safety positioning.
- Formal verification claims.

## Strategy conflict marker

Any materials framing Kubernetes or other demo connectors as the primary product wedge should be treated as outdated for the current phase.
