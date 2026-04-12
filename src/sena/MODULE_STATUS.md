# Module Status Map

This file makes supported vs experimental vs legacy module scope explicit.

## Supported module path (product commitment)

- `sena.policy.*`
- `sena.engine.*`
- `sena.api.*` (including runtime wiring in `sena.api.runtime`/`sena.api.app`)
- `sena.cli.*`
- `sena.integrations.jira`
- `sena.integrations.servicenow`
- `sena.integrations.persistence`
- `sena.audit.*`
- `sena.services.*` (where used by supported API/CLI flows)

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

Experimental modules may change without compatibility guarantees.

## Legacy

- `sena.legacy.*` (if present in a branch/history) is out of supported scope.
- Historical docs are in `docs/archive/`.
