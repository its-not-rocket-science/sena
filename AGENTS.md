# AGENTS.md

## Scope
This file applies to the entire repository.

## Working conventions
- Keep changes incremental and explicitly separate supported (`src/sena/*`) and legacy (`src/sena/legacy/*`) paths.
- Do not add new dependencies unless they materially improve security, operability, or testability.
- Prefer deterministic behavior and explicit failure over implicit fallback behavior.

## Validation checklist
- Run `pytest` for any code change.
- Run `ruff check src tests` for style checks.
- Keep README and docs in sync with code and API behavior.
