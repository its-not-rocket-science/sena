# Module Status Map

This file makes supported vs experimental vs legacy module scope explicit.

## Supported module path (product commitment)

- `sena.policy.*`
- `sena.engine.*`
- `sena.api.*`
- `sena.cli.*`
- `sena.integrations.jira`
- `sena.integrations.servicenow`
- `sena.integrations.persistence`
- `sena.audit.*`
- `sena.services.*` (where used by supported API/CLI flows)

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
