# Architecture Rules

This project enforces import boundaries to keep dependency direction stable and prevent layering drift.

## Allowed dependency direction

- `sena.api.routes` → `sena.services`
- `sena.services` → `sena.policy`, `sena.engine`, `sena.core`
- `sena.engine` → `sena.policy`, `sena.core`
- `sena.policy` → `sena.core`

## Forbidden dependency direction

- `sena.policy`, `sena.engine`, and `sena.core` **must not import** `sena.api`.
- `sena.services` **must not import** `sena.api.routes`.
- `sena.api.routes` **must not import directly** from `sena.policy`, `sena.engine`, or `sena.core`.

## Enforcement

The test suite includes an AST-based architecture guard (`tests/test_architecture_import_boundaries.py`) that fails CI when these boundaries are violated.

Run locally:

```bash
pytest
ruff check src tests
```

When adding new modules, preserve these rules by wiring dependencies through `sena.services` instead of importing across layers directly.
