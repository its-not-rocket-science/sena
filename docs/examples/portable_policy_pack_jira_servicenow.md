# Portable Policy Pack Example (Jira + ServiceNow)

This example shows how to enforce the same control logic across Jira and ServiceNow using SENA's normalized approval model.

## Included assets

- Policy pack: `src/sena/examples/policy_packs/portable_vendor_approvals/`
- Jira mappings: `src/sena/examples/integrations/jira_mappings.yaml`
- ServiceNow mappings: `src/sena/examples/integrations/servicenow_mappings.yaml`
- Simulation scenarios: `src/sena/examples/scenarios/simulation_scenarios.json`

## Why this is portable

Both connectors map source payloads into shared fields (`source_system`, `workflow_stage`, `requested_action`, `amount`, `vendor_verified`) before policy evaluation. The policy rules target these normalized fields, not vendor-specific payload paths.

## Run comparison and impact simulation

```bash
python -m sena.cli.main evaluate \
  --policy-dir src/sena/examples/policy_packs/portable_vendor_approvals \
  --compare-policy-dir src/sena/examples/policies \
  --simulate-scenarios src/sena/examples/scenarios/simulation_scenarios.json \
  --scenario examples/simulation_scenarios.json \
  --json
```

The simulation response includes grouped change summaries by:

- `source_system`
- `workflow_stage`
- `risk_category`

Use this output as release evidence during compliance review.

## Provenance and audit portability

Every decision includes:

- decision hash + input fingerprint,
- bundle name/version/schema,
- normalized source context,
- matched controls with reasons.

This makes it feasible to demonstrate that Jira and ServiceNow approvals are governed by the same deterministic control logic.
