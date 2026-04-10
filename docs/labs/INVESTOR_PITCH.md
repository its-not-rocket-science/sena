# Investor Pitch: SENA (Docs-Aligned)

## What SENA is today

SENA is an **alpha deterministic policy decision and audit evidence layer** for AI-assisted approvals.

## Primary wedge

SENA’s product wedge is one normalized policy decision layer across **Jira + ServiceNow approval events**, with deterministic outcomes and cryptographically verifiable audit records.

## Supported integration story

A team can define one policy bundle and apply it consistently to Jira and ServiceNow approval events, then verify resulting decision records through replay and audit verification workflows.

## Experimental bucket (not primary positioning)

The following are useful discovery/demo surfaces but not productized commitments in this phase:
- generic webhook mapping,
- Slack interactions,
- LangChain callback integration,
- Kubernetes admission demo assets.

## Honest maturity statement

SENA is alpha and not yet a full enterprise control plane by default. Missing/partial areas include built-in enterprise tenancy administration, full OIDC/RBAC admin UX, WORM-native replicated audit storage, and asynchronous large simulation orchestration.

## Non-goals (current phase)

- Becoming a generalized AI guardrails platform.
- Claiming broad connector coverage as current product depth.
- Presenting demo integrations as supported production commitments.
- Making formal verification claims.

## Why this framing

This narrative is intentionally constrained to what is implemented in `src/sena/*` and the currently supported integration paths.
