# Hard-Signal Engineering Scorecard

This repository uses a **hard-signal scorecard** as a pre-validation go/no-go gate for the supported SENA path (`src/sena/*` with Jira + ServiceNow).

The scorecard replaces vague maturity language with executable evidence checks.

## Run locally

```bash
python scripts/maturity_scorecard.py \
  --output-json artifacts/maturity_scorecard.json \
  --output-markdown artifacts/maturity_scorecard.md
```

## What this scorecard measures

Every signal is repository-derived and tied to engineering outcomes, not output volume:

1. **Replay corpus coverage on supported path**
   - Verifies replay fixtures include both Jira and ServiceNow supported connectors.
   - Verifies replay contract tests exist and fixtures are valid JSON.
2. **Adversarial audit verification coverage**
   - Verifies adversarial audit-chain tests exist and assert expected tamper/failure diagnostics.
3. **End-to-end supported-path test coverage**
   - Verifies explicit Jira + ServiceNow E2E webhook flow tests exist.
4. **Backup/restore verification drill coverage**
   - Verifies backup/restore drill script exists and executes in dry-run mode.
   - Verifies restore validation tests are present.
5. **Idempotency conflict handling coverage**
   - Verifies conflict semantics (`409`, stable conflict reason) are asserted in tests.
   - Verifies persistence layer exposes explicit `new/duplicate/conflict` outcomes.
6. **Authorization coverage on privileged routes**
   - Verifies privileged admin routes are explicitly tested for step-up and signed assertion enforcement.
7. **Migration safety test coverage**
   - Verifies migration checksum, rollback-boundary, duplicate-version, and legacy-forward tests exist.

## Anti-gaming design

The scorecard intentionally **does not** use:

- raw LOC,
- documentation count,
- total test count.

These are easy to inflate without improving safety or release quality.

## How to use for go/no-go decisions

Use the `gate.decision` field from `artifacts/maturity_scorecard.json`:

- `GO`: all required hard signals meet threshold.
- `NO_GO`: at least one required signal failed; external validation should be blocked until remediated.

Recommended release behavior before external validation:

1. Run the scorecard in CI.
2. Attach JSON + Markdown artifacts to the release candidate.
3. Treat any required signal failure as a blocker.
4. Record remediation PR(s), rerun scorecard, and require `GO` before proceeding.

## What the score means

A high score means the repository currently contains stronger executable evidence for supported-path determinism, verification, and recovery contracts.

## What the score does **not** mean

A high score does **not** prove:

- enterprise-complete security/compliance posture,
- environment-specific deployment correctness,
- elimination of manual security/legal/compliance review,
- elimination of independent external validation.
