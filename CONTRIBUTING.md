# Contributing to SENA

Thanks for helping improve SENA.

## Local quality checks

Run these checks before opening a PR:

```bash
ruff format --check src/sena tests
ruff check src tests
python scripts/check_architecture_concentration.py --check
pytest
```

Optional auto-format before committing:

```bash
ruff format src/sena tests
```

You can also run the combined helper target:

```bash
make quality
```

## Development setup

```bash
pip install -e .
pip install -e .[api,dev]
```

## Scope and behavior expectations

- Keep behavior deterministic.
- Avoid speculative rewrites.
- Preserve public behavior unless a bug fix is explicitly called out.
- Keep docs in sync with code and API behavior.

## Module growth guardrails (supported path)

SENA keeps maintainability guardrails intentionally lightweight. We measure only
coarse concentration signals (file LOC and branch density hotspots) for the core
supported surfaces in `src/sena/*`:

- evaluator (`src/sena/engine/evaluator*.py`)
- API app/runtime wiring (`src/sena/api/app.py`, `runtime.py`, `dependencies.py`)
- policy store + migrations (`src/sena/policy/store.py`, `migrations.py`, `scripts/migrations/*.sql`)
- integration connectors (`src/sena/integrations/{jira,servicenow,approval,persistence,registry}*.py`)

Generate a human-readable report and JSON artifact:

```bash
python scripts/check_architecture_concentration.py --output-json artifacts/architecture_concentration.json
```

Enforce guardrails locally/CI:

```bash
python scripts/check_architecture_concentration.py --check --output-json artifacts/architecture_concentration.json
```

### When to add a new module vs expand an existing module

Prefer **expanding an existing module** when:
- the new behavior belongs to the same bounded concern,
- it can share existing deterministic contracts without extra routing layers,
- and the file remains comfortably below concentration guardrail thresholds.

Prefer **adding a new module** when one of these is true:
- the existing module is becoming a hotspot (large file or branching-heavy),
- the change introduces a separable responsibility or lifecycle boundary,
- or the feature belongs to experimental/legacy namespaces rather than the supported path.

When splitting files, keep import roots stable where practical and avoid hidden
fallback behavior. If you add/relocate modules, update `src/sena/MODULE_STATUS.md`
so supported vs experimental vs legacy boundaries remain explicit.
