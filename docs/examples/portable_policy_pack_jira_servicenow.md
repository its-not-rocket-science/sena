# Flagship Portable Workflows (Jira + ServiceNow)

This guide upgrades the integration story into two production-style workflows that share core policy logic while using source-specific mappings.

## Core portability claim

Both workflows normalize source payloads into the same governance facts (`risk_score`, `environment`, `privileged_change`, `emergency_change`, `cab_review_evidence_id`) and evaluate a shared policy bundle (`acme-change-governance`).

Because the policy bundle is source-agnostic, governance changes happen once in SENA policy, not twice in Jira workflow rules and ServiceNow flow logic.

---

## Workflow A — Jira approval gating (high-risk change/payment approval)

### Realistic mapping
- Mapping file: `examples/design_partner_reference/integration/jira_mapping.yaml`
- Event type: `jira:issue_updated`
- Source: Jira issue custom fields for risk score, emergency/privileged flags, CAB evidence
- Output action: `approve_change_request`

### Scenario fixtures
- High-risk missing CAB evidence: `tests/fixtures/integrations/jira/high_risk_change_missing_cab.json`
- Low-risk with CAB evidence: `tests/fixtures/integrations/jira/low_risk_change_with_cab.json`

### Smoke test (local)
```bash
pytest tests/test_flagship_workflows.py -k "workflow_a_jira"
```

### End-to-end behavior
- Happy path: low-risk change with CAB evidence -> `ALLOW`
- Failure mode: high-risk change without CAB evidence -> `BLOCK`
- Integration hard failure mode: missing actor identity -> deterministic error

### Runbook
1. Ensure dependencies are installed (`pip install -r requirements.txt`).
2. Run the workflow-specific smoke tests shown above.
3. Generate evidence pack (below) and inspect `artifacts/integration_examples/jira_event_*.json`.
4. Use deterministic decision payloads as buyer-facing proof of policy portability.

### Expected operational failure modes
- Unsupported Jira event type
- Missing required custom fields
- Duplicate webhook delivery ID
- Invalid webhook signature (if shared-secret verifier enabled)

### Buyer-facing value vs embedding rules directly in Jira
- Central policy updates without editing Jira transitions/screens.
- Deterministic audit trail tied to rule IDs and bundle version.
- Faster control rollout across additional systems without re-implementing logic.

---

## Workflow B — ServiceNow change approval (escalation + callback loop)

### Realistic mapping
- Mapping file: `src/sena/examples/integrations/servicenow_mappings.yaml`
- Event type: `change_approval.requested`
- Output action: `approve_vendor_payment` (portable action type used across connectors)
- Deterministic callback: `send_decision` emits stable payload for Flow Designer/Business Rules

### Scenario fixtures
- Escalation candidate: `tests/fixtures/integrations/servicenow/out_of_hours_change.json`
- Block case: `tests/fixtures/integrations/servicenow/missing_cab_review_evidence.json`

### Smoke test (local)
```bash
pytest tests/test_flagship_workflows.py -k "workflow_b_servicenow"
```

### End-to-end behavior
- Happy path: out-of-hours change -> `ESCALATE` + callback payload `deterministic=true`
- Failure mode: missing CAB evidence -> `BLOCK`
- Integration hard failure mode: missing actor identity -> deterministic error

### Runbook
1. Export mapping config:
   ```bash
   export SENA_SERVICENOW_MAPPING_CONFIG=src/sena/examples/integrations/servicenow_mappings.yaml
   ```
2. Run workflow-specific smoke tests.
3. Run evidence pack generation and inspect `integration_examples` output for callback payloads.
4. Wire callback payload to ServiceNow Flow Designer branch logic.

### Expected operational failure modes
- Unsupported ServiceNow event type
- Missing required fields in payload/mapping
- Duplicate delivery ID replay
- Policy bundle mismatch

### Buyer-facing value vs embedding rules directly in ServiceNow
- Source workflow remains thin (collect/forward facts), policy remains centralized.
- Escalation and block criteria are portable to Jira and future systems.
- Callback payload is deterministic and easy to consume in existing ServiceNow automations.

---

## Evidence-pack inclusion

Generate evidence artifacts with:

```bash
python scripts/generate_evidence_pack.py --output-dir /tmp/sena-flagship-pack --clean
```

Expected flagship evidence:
- `artifacts/integration_examples/jira_event_*.json`
- `artifacts/integration_examples/servicenow_event_*.json`
- `artifacts/evaluation_traces/*.json`
- `artifacts/review_packages/*.json`

These files are buyer-facing evidence that identical policy intent is enforced across both systems.
