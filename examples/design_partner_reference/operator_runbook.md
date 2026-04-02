# Operator Runbook: ServiceNow Change Governance Pack

## Purpose
Operate SENA as a deterministic policy control plane for ServiceNow change approvals, with Jira portability checks.

## Preconditions
- Python 3.11+
- `pip install -e .[dev]`
- Run from repo root (`/workspace/sena`)

## 1) Run end-to-end pack
```bash
PYTHONPATH=src python examples/design_partner_reference/run_reference.py
```

## 2) Check promotion gate evidence
- `examples/design_partner_reference/artifacts/simulation-report.json`
- `examples/design_partner_reference/artifacts/promotion-validation.json`
- `examples/design_partner_reference/artifacts/release-manifest.json`

Gate is green when:
- signature verification is valid,
- simulation changed scenarios are understood,
- promotion validation is `valid=true`.

## 3) Validate audit chain
```bash
python -m sena.cli.main --help >/dev/null
```
Then inspect:
- `examples/design_partner_reference/artifacts/audit-chain-verification.json`
- `examples/design_partner_reference/artifacts/audit/audit.jsonl`

## 4) Verify portability signal
Inspect `examples/design_partner_reference/artifacts/normalized-event-examples.json`.
- ServiceNow and Jira events normalize into one policy contract.
- Both are evaluated against the same active policy bundle.

## 5) Verify replay determinism and update drift
Inspect:
- `examples/design_partner_reference/artifacts/replay-report-stable.json`
- `examples/design_partner_reference/artifacts/replay-report-policy-update.json`

Expected:
- stable replay has zero changed outcomes,
- policy update replay shows the emergency privileged change tightening.

## 6) If malformed events arrive
Use deterministic failures:
- missing event type → reject with explicit integration error,
- missing required fields → reject with explicit integration error.

Reference fixtures:
- `examples/design_partner_reference/fixtures/malformed/servicenow_missing_event_type.json`
- `examples/design_partner_reference/fixtures/malformed/servicenow_missing_required_fields.json`
