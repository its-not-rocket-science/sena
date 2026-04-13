# Flagship Workflow Example: Emergency Change Approval (ServiceNow)

This example is the default SENA story: one high-risk ServiceNow change approval event is normalized, evaluated by policy, written to audit, and exported as a deterministic replay artifact.

## Run the flagship example

```bash
PYTHONPATH=src python examples/flagship/run_flagship.py
```

Expected result in `examples/flagship/artifacts/summary.json`:
- `actual_outcome` is `BLOCKED`

## Artifacts produced

- `artifacts/normalized-event.json`
- `artifacts/decision-trace.json`
- `artifacts/canonical-replay-artifact.json`
- `artifacts/audit-verification.json`
- `artifacts/summary.json`

## CLI path

```bash
python -m sena.cli.main \
  examples/flagship/evaluate_payload.json \
  --policy-dir examples/design_partner_reference/policy_bundles/active \
  --json
```

## API path

```bash
SENA_POLICY_DIR=examples/design_partner_reference/policy_bundles/active \
SENA_SERVICENOW_MAPPING_CONFIG=examples/design_partner_reference/integration/servicenow_mapping.yaml \
PYTHONPATH=src python -m uvicorn sena.api.app:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/integrations/servicenow/webhook \
  -H 'content-type: application/json' \
  -H 'x-servicenow-delivery-id: flagship-workflow-001' \
  --data @examples/flagship/servicenow_webhook_payload.json
```
