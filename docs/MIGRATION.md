# Migration Notes: Legacy Prototype → Compliance Engine

## What moved

Legacy modules were moved under `src/sena/legacy`:

- `src/sena/core/types.py` → `src/sena/legacy/core/types.py`
- `src/sena/production_systems/experta_adapter.py` → `src/sena/legacy/production_systems/experta_adapter.py`
- `src/sena/evolutionary/deap_adapter.py` → `src/sena/legacy/evolutionary/deap_adapter.py`
- `src/sena/llm/simulated_adapter.py` → `src/sena/legacy/llm/simulated_adapter.py`
- `src/sena/orchestrator/sena.py` → `src/sena/legacy/orchestrator/sena.py`

Compatibility shims remain at the old import paths but emit deprecation warnings.

## What is now primary

Primary path:
- `sena.policy.*`
- `sena.engine.evaluator`
- `sena.cli.main`
- `sena.api.app`

## What is deprecated

Anything under `sena.legacy` (and old shim imports) is historical/experimental and not the recommended path for enterprise compliance workflows.

## Eval contradiction removal

Dynamic `eval(...)` usage exists only in legacy modules. The supported compliance engine evaluates structured conditions through an allowed-operator interpreter.


## Import guardrails

To reduce accidental dependency on legacy code paths:

- Legacy imports emit explicit deprecation warnings by default.
- Set `SENA_STRICT_LEGACY_IMPORTS=true` to fail legacy imports immediately (`ImportError`).
- Set `SENA_RUNTIME_MODE=production` to block `sena.legacy` imports at runtime (`RuntimeError`).
- A temporary override exists: `SENA_ALLOW_LEGACY_IN_PRODUCTION=true` (use only during tightly controlled migration windows).

