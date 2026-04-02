# Repository Maturity Scorecard

SENA includes a repository-derived scorecard to measure **technical maturity progress from alpha toward pilot-ready**.

It is not a claim that SENA is enterprise-complete today.

## Run locally

```bash
python scripts/maturity_scorecard.py --output-json artifacts/maturity_scorecard.json
```

## What the scorecard is for

- Keep contributors focused on supported architecture (`src/sena/*`).
- Track objective progress on determinism, lifecycle governance, testing, and operational recovery.
- Prevent vanity metrics from being mistaken for product maturity.

## Metrics

The scorecard reports these metrics (0-100 each), then computes an unweighted average:

1. API layer complexity / file concentration
2. Service-layer coverage
3. Failure-mode test count
4. Migration coverage
5. Persistence/audit recovery coverage
6. Documentation completeness for flagship workflows
7. Evidence-pack generation success
8. Replay/drift coverage for AI-assisted actions

## Interpretation guidance

- High scorecard results indicate stronger **pilot-readiness trajectory**.
- They do **not** by themselves imply full enterprise controls (for example: built-in OIDC/RBAC tenancy, WORM storage, or full control-plane UX).
- Product positioning remains anchored to deterministic Jira + ServiceNow governance depth, with generic webhook and Slack marked experimental.
