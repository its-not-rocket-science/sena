# Flagship Portable Workflow Example (Jira + ServiceNow)

This is the flagship example for SENA’s current wedge: **portable deterministic policy governance across Jira + ServiceNow**.

## Integration status

- **Supported integrations:** Jira + ServiceNow
- **Experimental integrations:** generic webhook + Slack (not covered in this flagship guide)

## Portability claim

Both sources normalize into one shared policy context and evaluate against the same policy bundle.

- Jira mapping: `examples/design_partner_reference/integration/jira_mapping.yaml`
- ServiceNow mapping: `examples/design_partner_reference/integration/servicenow_mapping.yaml`
- Shared bundle: `examples/design_partner_reference/policy_bundles/active/`

Because policy is source-agnostic, governance changes are made once in SENA policy, not separately in each workflow tool.

## Example fixtures

- Jira low risk with CAB evidence: `examples/design_partner_reference/fixtures/jira_event_low_risk_with_cab.json`
- Jira high risk missing CAB: `examples/design_partner_reference/fixtures/jira_event_high_risk_missing_cab.json`
- ServiceNow low risk with CAB: `examples/design_partner_reference/fixtures/servicenow_event_low_risk_with_cab.json`
- ServiceNow emergency privileged no chain: `examples/design_partner_reference/fixtures/servicenow_event_emergency_privileged_no_chain.json`

## Run the reference flow

```bash
PYTHONPATH=src python examples/design_partner_reference/run_reference.py
```

Generated artifacts include:
- `examples/design_partner_reference/artifacts/evaluation-results.json`
- `examples/design_partner_reference/artifacts/simulation-report.json`
- `examples/design_partner_reference/artifacts/promotion-validation.json`
- `examples/design_partner_reference/artifacts/audit-chain-verification.json`

## Expected behavior

- Low-risk with required evidence: `APPROVED`
- High-risk missing required evidence: `BLOCKED`
- Emergency privileged without control chain: `BLOCKED`

## Why this matters

This walkthrough demonstrates SENA’s near-term product value:
- deterministic outcomes,
- shared policy logic across two enterprise systems,
- release evidence artifacts for compliance/risk reviews.
