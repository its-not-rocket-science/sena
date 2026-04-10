# Docs Consistency Report (April 2026)

## Why this update was made

Multiple strategy documents had drifted into conflicting narratives (for example, Kubernetes-first GTM language vs. Jira+ServiceNow supported-path language). This update aligns core docs and investor/demo docs to one implementation-backed product story.

## Canonical narrative now used across edited docs

1. **Primary wedge:** one normalized policy decision layer for Jira + ServiceNow approvals.
2. **Supported integration story:** one shared policy model with deterministic outcomes and replay/audit evidence across Jira + ServiceNow.
3. **Experimental bucket:** generic webhook, Slack, LangChain callback, and Kubernetes demo assets are evaluation-only.
4. **Honest maturity statement:** alpha; not yet a full enterprise control plane.
5. **Non-goals:** no broad connector marketplace claim, no generalized AI safety repositioning, no formal verification claims.

## What changed

- Rewrote `ROADMAP.md` to remove Kubernetes-first primary strategy language and align priorities to supported integration hardening.
- Rewrote `docs/CONTROL_PLANE.md`, `docs/ARCHITECTURE.md`, and `docs/TECHNICAL_MATURITY_PLAN.md` to use a shared narrative frame and explicit conflict markers.
- Rewrote investor/fundraising collateral and moved it under `docs/labs/` to keep core product docs separate from demo narratives.
- Updated `README.md` to keep one current truth path and redirect experimental/investor material to `docs/LABS.md`.
- Updated `examples/k8s_admission_demo/INVESTOR_DECK.md` and `examples/k8s_admission_demo/DEMO_SCRIPT.md` to clearly mark demo status as experimental.

## Why these changes are truthful to code

Supported API/runtime integration surfaces in `src/sena/*` clearly include Jira and ServiceNow as first-class normalized endpoints, while generic webhook and Slack remain separate, less-committed integration surfaces. Kubernetes materials live under `examples/` and are therefore represented as demos, not primary supported product depth.
