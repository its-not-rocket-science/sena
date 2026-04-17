# Module Status Map

This file makes supported vs experimental vs legacy scope explicit and shows the
recommended package entry points for new contributors.

## Package map (recommended import roots)

- `sena.core_policy_engine` → core policy engine
- `sena.supported_integrations` → supported integrations
- `sena.runtime` → runtime/API/CLI/service wiring
- `sena.audit_evidence` → audit and replay evidence
- `sena.experimental` → evaluation-only/unstable modules
- `sena.legacy` → reserved legacy namespace (intentionally not shipped)

## Supported module path (product commitment)

- `sena.policy.*`
- `sena.engine.*`
- `sena.core.*`
- `sena.api.*` (including runtime wiring in `sena.api.runtime`/`sena.api.app`)
- `sena.cli.*`
- `sena.audit.*`
- `sena.services.*` (where used by supported API/CLI flows)
- `sena.integrations.jira`
- `sena.integrations.servicenow`
- `sena.integrations.persistence`
- `sena.integrations.approval`
- `sena.integrations.registry`

Supported reliability/admin surfaces are the versioned API routes under:
- `sena.api.routes.integrations` (`/v1/admin/*` and connector outbound reliability endpoints)
- `sena.services.reliability_service` (queueing, circuit breaker, and SLO payload contracts)

Canonical artifact plumbing for replay/determinism is maintained in:
- `sena.services.integration_service` (`canonical_replay_payload`, hash contract)

## Experimental modules (evaluation-only)

- `sena.integrations.webhook`
- `sena.integrations.slack`
- `sena.integrations.langchain.*`
- `sena.llm.*`
- `sena.evolutionary.*`
- `sena.production_systems.*`
- `sena.orchestrator.*`
- `sena.monitoring.*`

Experimental modules may change without compatibility guarantees.

## Legacy

- `sena.legacy.*` is intentionally not shipped in this repository state.
- Historical docs are in `docs/archive/`.
