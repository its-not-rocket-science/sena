# Design Partner Reference: ServiceNow Change Approval

This reference implementation provides a **single realistic vertical slice** through SENA's supported path:

1. ServiceNow integration event normalization.
2. Candidate-to-active policy lifecycle promotion.
3. Signed release manifest generation and verification.
4. Simulation gate before promotion.
5. Runtime evaluation and decision delivery.
6. Tamper-evident audit sink records.
7. Decision review package generation.

## Scenario

A design partner uses ServiceNow for production change approvals. SENA evaluates change approval events with deterministic policy controls:

- **High risk + missing CAB evidence** is blocked.
- **Privileged production changes** are escalated.
- **Low-risk CAB-reviewed changes** are auto-allowed.
- Newly introduced active policy adds a strict block for emergency privileged changes with no approver chain.

## Files and Structure

- `integration/servicenow_mapping.yaml`: real integration mapping.
- `fixtures/servicenow_event_*.json`: workflow events from source system.
- `fixtures/simulation_scenarios.json`: simulation gate inputs.
- `policy_bundles/candidate/*`: pre-promotion bundle.
- `policy_bundles/active/*`: promotion target bundle.
- `run_reference.py`: end-to-end orchestration.
- `artifacts/*`: generated outputs for auditability and review.

## Run locally

From repository root:

```bash
PYTHONPATH=src python examples/design_partner_reference/run_reference.py
```

## What gets generated

- `artifacts/release-manifest.json` – signed policy bundle release artifact.
- `artifacts/simulation-report.json` – pre-promotion simulation results.
- `artifacts/promotion-validation.json` – lifecycle + signature gate decision.
- `artifacts/evaluation-results.json` – end-to-end evaluation results.
- `artifacts/audit/audit.jsonl` (+ manifest/segments) – tamper-evident audit records.
- `artifacts/audit-chain-verification.json` – chain verification output.
- `artifacts/review_packages/*.json` – generated decision review packages.

## Why this is a depth example

This is intentionally a **narrow but deep** story: one integration domain, one policy domain, one promotion flow, one audit trail, and one review output package. It demonstrates how a design partner can run a controlled policy release process with deterministic governance and evidence.
