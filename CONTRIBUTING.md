# Contributing to SENA

Thanks for helping improve SENA.

## Local quality checks

Run these checks before opening a PR:

```bash
ruff format --check src/sena tests
ruff check src tests
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
