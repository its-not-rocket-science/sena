# Flagship Workflow: Emergency Change Approval (ServiceNow-first, Jira-portable)

This is the **default end-to-end SENA story**.

It uses only supported code paths and demonstrates one realistic high-risk workflow:

1. Inbound normalized event (ServiceNow webhook)
2. Policy evaluation
3. Deterministic outcome (`BLOCKED`)
4. Replay artifact export
5. Audit chain verification
6. Operational runbook for day-2 operations

## Why this is the flagship workflow

- **Clear business value:** prevent unsafe emergency privileged production changes from auto-approval.
- **Supported depth:** built on `src/sena/integrations/servicenow.py`, `src/sena/engine/*`, `src/sena/policy/*`, and `src/sena/audit/*`.
- **Deterministic proof:** same normalized event + same active bundle gives the same outcome.
- **Operator-ready evidence:** JSON artifacts can be handed to compliance/audit teams.

## Scenario

Input event: ServiceNow change approval request with these risk signals:

- `environment=production`
- `service_tier=tier0`
- `flags.privileged=true`
- `flags.emergency=true`
- missing `approver_chain`

Expected policy outcome with the active design-partner bundle:

- `BLOCKED`

## Quickstart (copy/paste)

From repo root:

```bash
pip install -e .[dev]
```

### 1) Run the flagship example end to end

```bash
PYTHONPATH=src python examples/flagship/run_flagship.py
```

Inspect key artifacts:

```bash
cat examples/flagship/artifacts/summary.json
cat examples/flagship/artifacts/audit-verification.json
```

### 2) Run the same scenario through CLI

```bash
python -m sena.cli.main \
  examples/flagship/evaluate_payload.json \
  --policy-dir examples/design_partner_reference/policy_bundles/active \
  --json
```

### 3) Run the same scenario through API integration endpoint

Terminal A:

```bash
SENA_POLICY_DIR=examples/design_partner_reference/policy_bundles/active \
SENA_SERVICENOW_MAPPING_CONFIG=examples/design_partner_reference/integration/servicenow_mapping.yaml \
PYTHONPATH=src python -m uvicorn sena.api.app:app --host 127.0.0.1 --port 8000
```

Terminal B:

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/integrations/servicenow/webhook \
  -H 'content-type: application/json' \
  -H 'x-servicenow-delivery-id: flagship-workflow-001' \
  --data @examples/flagship/servicenow_webhook_payload.json
```

## Artifact map

Running `examples/flagship/run_flagship.py` generates:

- `examples/flagship/artifacts/normalized-event.json`
  - proof of inbound normalized event contract
- `examples/flagship/artifacts/decision-trace.json`
  - deterministic policy evaluation trace and outcome
- `examples/flagship/artifacts/canonical-replay-artifact.json`
  - replay-stable decision artifact
- `examples/flagship/artifacts/audit-verification.json`
  - audit chain integrity verification result
- `examples/flagship/artifacts/summary.json`
  - compact operator-facing outcome summary

## Operational runbook

### Preconditions

- Python 3.11+
- dependencies installed with `pip install -e .[dev]`
- repo root is current working directory

### Standard operator flow

1. Run flagship workflow script.
2. Confirm `summary.json.actual_outcome == "BLOCKED"`.
3. Confirm `audit-verification.json.valid == true`.
4. Archive the artifact directory for ticket/compliance handoff.

### Deterministic verification checklist

- Re-run `examples/flagship/run_flagship.py` with no code/policy changes.
- Confirm repeated runs remain `BLOCKED`.
- Compare canonical replay payload hashes in `canonical-replay-artifact.json`.

### Incident handling

If outcome differs from expected (`BLOCKED`):

1. Check active policy bundle path and version.
2. Check mapping configuration path (`SENA_SERVICENOW_MAPPING_CONFIG`).
3. Re-run CLI path with `examples/flagship/evaluate_payload.json` to isolate integration issues.
4. Inspect `decision-trace.json` matched rules and rationale.

## Related files

- Example entrypoint: `examples/flagship/run_flagship.py`
- Example payloads: `examples/flagship/*.json`
- Supported policy bundle: `examples/design_partner_reference/policy_bundles/active`
- ServiceNow mapping: `examples/design_partner_reference/integration/servicenow_mapping.yaml`
