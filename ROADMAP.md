# SENA Roadmap (Aligned Product Narrative)

## Product narrative anchor (April 2026)

SENA’s near-term product is intentionally narrow:

- **Primary wedge:** one normalized policy decision layer for **Jira + ServiceNow approval events**.
- **Supported integration story:** teams can apply one policy bundle across Jira and ServiceNow and receive deterministic outcomes plus replayable audit evidence.
- **Experimental bucket:** generic webhook, Slack interactions, LangChain callback, and Kubernetes admission demo assets are evaluation-only and not productized commitments.

## Honest maturity statement

SENA is **alpha**. The deterministic decision engine and evidence flows are implemented, but the platform is **not** yet a full enterprise control plane (for example: full tenant admin plane, OIDC/RBAC UI, WORM-native storage, and asynchronous large-job orchestration are not complete).

## 30-day roadmap priorities

1. Harden Jira + ServiceNow integration runbooks and deterministic fixture coverage.
2. Enforce fail-closed promotion gates requiring simulation + diff evidence.
3. Improve operational durability (SQLite durability checks, backup/restore drills, audit verification recovery checks).

## Non-goals for this phase

- No broad connector marketplace expansion before Jira + ServiceNow depth targets are met.
- No repositioning as generalized AI safety software.
- No formal verification claims.
- No claim that Kubernetes demo assets are the primary production integration.

## Conflicting strategy language removed

The prior roadmap emphasized a Kubernetes-first GTM and broad investor milestones as primary product strategy. That language is intentionally replaced here with implementation-backed priorities aligned to the supported code paths and docs canon.
