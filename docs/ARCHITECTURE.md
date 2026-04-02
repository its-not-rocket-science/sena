# SENA Architecture (Supported vs Legacy)

## Architecture intent

SENA is a deterministic policy control plane for AI-assisted approval workflows, with **Jira + ServiceNow normalization** as the current productized integration wedge.

## Supported architecture (source of truth)

Supported code lives in `src/sena/*`:

1. Policy parsing/loading (`sena.policy.parser`)
2. Policy validation (`sena.policy.validation`)
3. Safe interpretation (`sena.policy.interpreter`)
4. Deterministic evaluation (`sena.engine.evaluator`)
5. API/CLI runtime surfaces (`sena.api.*`, `sena.cli.main`)

Legacy code under `src/sena/legacy/*` is not part of supported claims.

## Decision flow

1. Normalize input event into policy context.
2. Evaluate rule conditions with allowed operators only.
3. Apply precedence:
   - inviolable block,
   - ordinary block,
   - escalate,
   - default decision (`APPROVED` if unspecified).
4. Emit deterministic trace + review/audit metadata.

## Integration architecture status

### Supported integrations (today)
- Jira: `POST /v1/integrations/jira/webhook`
- ServiceNow: `POST /v1/integrations/servicenow/webhook`

### Experimental integrations
- Generic webhook mapper: `POST /v1/integrations/webhook`
- Slack interactions: `POST /v1/integrations/slack/interactions`

Experimental integrations are intentionally marked non-contractual for this alpha phase.

## Governance evidence architecture

- Bundle diff + promotion validation APIs.
- Scenario simulation and replay/drift evaluation.
- Hash-linked audit records with verification endpoint.

This is release-evidence infrastructure, not a full enterprise governance suite.

## Maturity boundary

SENA is **alpha** today. Pilot-ready objectives are documented in `docs/TECHNICAL_MATURITY_PLAN.md` and `ROADMAP.md`.

Not yet built-in:
- enterprise tenancy and OIDC/RBAC admin plane,
- replicated/WORM-native audit persistence,
- asynchronous large simulation jobs,
- policy authoring UI.
