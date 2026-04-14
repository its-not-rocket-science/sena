# SENA Control Plane (Alpha)

Read `READINESS.md` for the canonical maturity model and explicit production-grade gaps.

Terminology follows README: `supported`, `experimental`, `labs/demo`, and `legacy`.

## Supported product (current scope)

SENA is an **alpha control-plane core for Jira + ServiceNow approval decisioning**.

The supported path is concrete and implemented: ingest Jira/ServiceNow approval events, normalize them into one policy context, evaluate deterministically against versioned bundles, and return machine-actionable outcomes with replayable evidence.

- Outcomes: `APPROVED`, `BLOCKED`, `ESCALATE_FOR_HUMAN_REVIEW`
- Same policy semantics across Jira and ServiceNow
- Deterministic replay artifacts + hash-linked audit verification

## Implemented capabilities

1. Deterministic policy evaluation core.
2. Jira + ServiceNow normalized integration routes.
3. Bundle diff, simulation, and promotion-validation release evidence primitives.
4. Hash-linked audit records with verification endpoints.
5. Policy lifecycle state transitions.

## Maturity statement

SENA is **alpha**. Pilot suitability and production gaps are defined in `READINESS.md`; this document only describes the implemented control-plane scope.

## Non-goals (current phase)

- Broad connector marketplace expansion before Jira + ServiceNow depth hardening.
- Generalized AI safety positioning as the primary product narrative.
- Formal verification claims.

## Strategy conflict marker

Any materials framing Kubernetes or other labs/demo connectors as the primary product wedge are historical.
