# Canonical Integration Pack: ServiceNow Change Governance (+ Jira Portability)

This pack is the canonical SENA demo for the current product wedge.

## What this pack proves

- **Normalization:** ServiceNow events normalize into SENA's approval policy contract.
- **Determinism:** same replay inputs produce stable outcomes.
- **Policy portability:** same active policy evaluates normalized Jira + ServiceNow examples.
- **Promotion gating:** candidate → active changes are simulation-gated and signature-verified.
- **Audit verification:** generated audit chain verifies tamper-evident records.

## Pack contents

- Deterministic mapping configs:
  - `integration/servicenow_mapping.yaml`
  - `integration/jira_mapping.yaml`
- Realistic fixtures:
  - `fixtures/servicenow_event_*.json`
  - `fixtures/jira_event_*.json`
  - `fixtures/malformed/*.json`
- Simulation scenarios:
  - `fixtures/simulation_scenarios.json`
- Replay examples:
  - `fixtures/replay_cases.json`
- Policy bundles:
  - `policy_bundles/candidate/*`
  - `policy_bundles/active/*`
- Operator assets:
  - `operator_runbook.md`
  - `demo_15m.sh`

## Run locally

```bash
PYTHONPATH=src python examples/design_partner_reference/run_reference.py
```

## Generated release evidence examples

- `artifacts/release-manifest.json`
- `artifacts/simulation-report.json`
- `artifacts/promotion-validation.json`
- `artifacts/evaluation-results.json`
- `artifacts/normalized-event-examples.json`
- `artifacts/replay-report-stable.json`
- `artifacts/replay-report-policy-update.json`
- `artifacts/audit-chain-verification.json`
- `artifacts/review_packages/*.json`

## 15-minute demo

```bash
examples/design_partner_reference/demo_15m.sh
```

This runs the full pack and prints key gate/replay/portability checks.
