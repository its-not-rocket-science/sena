# SENA Technical Maturity Plan (Alpha → Pilot-Ready)

## Coherent product narrative

- **Primary wedge:** normalized deterministic policy decisions for Jira + ServiceNow approvals.
- **Supported integration story:** one bundle, deterministic outcomes, replay/audit evidence across Jira + ServiceNow.
- **Experimental bucket:** generic webhook, Slack, LangChain callback, Kubernetes demo (evaluation-only).

## Honest maturity statement

SENA is **alpha**. The deterministic engine and evidence workflows are implemented, but pilot-ready enterprise operations are still in progress.

## Top priorities for pilot-ready progress

1. **Integration depth hardening (Jira + ServiceNow)**
   - Fixture/edge-case coverage,
   - deterministic failure contracts,
   - partner-facing runbooks.
2. **Promotion governance gates**
   - fail-closed simulation-backed promotions,
   - required evidence artifacts,
   - explicit audited break-glass flow.
3. **Operational trust baseline**
   - durability/migration safety,
   - backup/restore and audit verification drills,
   - deployment hardening and observability.

## Non-goals (this phase)

- Broad connector marketplace expansion before supported-path depth goals.
- Generalized AI safety repositioning.
- Formal verification guarantees.
- Claiming full enterprise control-plane UX/IAM maturity.

## Conflict marker

Prior planning language that elevates demo connectors to primary GTM should be treated as superseded by this maturity plan.
