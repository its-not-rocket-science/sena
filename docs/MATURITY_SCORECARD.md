# Repository Maturity Scorecard

SENA includes an objective maturity scorecard that is computed directly from repository state and executable checks.

The scorecard is designed to:

- push contributors toward the supported architecture (`src/sena/*`),
- reward coverage, migration readiness, audit/recovery readiness, and deterministic release evidence,
- avoid vanity metrics (for example, raw line-count growth does not improve most scores).

## Run locally

```bash
python scripts/maturity_scorecard.py --output-json artifacts/maturity_scorecard.json
```

The command prints the full scorecard and writes a JSON artifact.

## Metrics

The scorecard reports these metrics (0-100 each), then computes an unweighted average:

1. **API layer complexity / file concentration**
   - Derived from AST branching density in `src/sena/api/*` plus concentration of non-comment LOC in the largest API file.
   - Rewards lower complexity and less surface-area concentration in one file.
2. **Service-layer coverage**
   - Measures how many `src/sena/services/*.py` modules are referenced by tests.
3. **Failure-mode test count**
   - Counts test functions with failure-mode keywords (`fail`, `error`, `invalid`, `unsupported`, `drift`, `disaster`, `recovery`, `guard`).
4. **Migration coverage**
   - Measures how many SQL migration scripts under `scripts/migrations/*.sql` are referenced in tests.
5. **Persistence/audit recovery coverage**
   - Checks for required source modules, docs, and test files for persistence and audit recovery paths.
6. **Documentation completeness for flagship workflows**
   - Requires flagship docs to exist and be discoverable from `README.md`.
7. **Evidence-pack generation success**
   - Executes `scripts/generate_evidence_pack.py` and validates successful deterministic artifact output.
8. **Replay/drift coverage for AI-assisted actions**
   - Verifies replay/drift test coverage and AI-assisted scenario fixtures.

## CI integration and historical tracking

The GitHub Actions workflow at `.github/workflows/maturity-scorecard.yml`:

- runs the scorecard on every `push` and `pull_request`,
- uploads the JSON artifact (`maturity-scorecard-<run-id>`),
- uploads a timestamped history snapshot (`maturity-scorecard-history-<run-id>`).

Together these artifacts provide time-series tracking across runs without requiring mutable in-repo history files.

## Why this avoids vanity metrics

The scorecard intentionally prioritizes architecture and operational readiness signals:

- executable checks (evidence-pack generation),
- tests and migration references,
- replay/drift and recovery readiness,
- documentation discoverability for flagship workflows,
- complexity and concentration constraints in API surface.

As a result, adding more code without improving reliability/coverage does not automatically increase score.
