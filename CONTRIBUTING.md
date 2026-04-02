# Contributing to SENA

Thanks for helping improve SENA. This repository keeps a strict separation between:

- **Supported path:** `src/sena/*` (active product surface)
- **Legacy path:** `src/sena/legacy/*` (compatibility only; avoid drive-by edits)

When in doubt, prefer incremental changes in supported-path modules and matching tests.

## Local quality checks

Run these checks before opening a PR:

```bash
ruff format --check src/sena tests --exclude src/sena/legacy
ruff check src/sena tests
pytest
```

Optional auto-format before committing:

```bash
ruff format src/sena tests --exclude src/sena/legacy
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
