# ServiceNow Integration Runbook

## Why this integration exists
SENA's ServiceNow integration is designed for enterprise change governance workflows where approvals are high-risk, auditable, and must be deterministic. It turns ServiceNow change approval requests into normalized `ActionProposal` objects and returns a deterministic callback payload that ServiceNow Flow Designer or Business Rules can consume directly.

## Supported flow
1. ServiceNow sends a change-approval event to `POST /v1/integrations/servicenow/webhook`.
2. SENA normalizes the request into a shared `NormalizedApprovalEvent` model used by both Jira and ServiceNow connectors.
3. SENA maps that event to `ActionProposal` and evaluates policies.
4. SENA returns a deterministic decision response and a callback payload shape suitable for source workflow consumption.

## Configuration
```bash
export SENA_SERVICENOW_MAPPING_CONFIG=src/sena/examples/integrations/servicenow_mappings.yaml
```

## Normalized event model (exact fields)
```json
{
  "delivery_id": "string",
  "source_system": "servicenow",
  "event_type": "change_approval.requested",
  "source_record_id": "sys_id",
  "request_id": "CHG...",
  "actor_id": "requester identifier",
  "actor_role": "optional requester role",
  "event_timestamp": "RFC3339 UTC",
  "attributes": {"...": "mapped source fields"},
  "source_metadata": {"servicenow_table": "change_request", "servicenow_change_number": "CHG..."}
}
```

## Mapping philosophy
- Keep mapping deterministic with explicit required-field checks.
- Fail closed on malformed payloads and mapping mismatches.
- Keep approval semantics in SENA policy bundles, not embedded inside source workflow branching logic.

### Why this is better than embedding rules directly in ServiceNow workflows
- **Single policy authority:** one policy bundle can govern multiple systems (ServiceNow + Jira).
- **Deterministic precedence and traceability:** SENA's evaluator provides stable precedence behavior and machine-readable audit records.
- **Safer change management:** source workflow only gathers and forwards facts; SENA enforces reusable governance logic.
- **Portability:** the same control can be applied across tools without re-implementing Flow Designer logic per integration.

## Decision callback payload
`send_decision` emits:
```json
{
  "schema_version": "1",
  "source_system": "servicenow",
  "decision_id": "dec_xxx",
  "request_id": "CHG...",
  "action_type": "approve_vendor_payment",
  "decision": "Decision dec_xxx: BLOCKED ...",
  "matched_rule_ids": ["RULE-1"],
  "status": "completed",
  "deterministic": true
}
```

## Integration-specific examples covered
Fixtures are provided for:
- emergency changes (`emergency_change.json`)
- privileged changes (`privileged_change.json`)
- out-of-hours changes (`out_of_hours_change.json`)
- missing approver chain (`missing_approver_chain.json`)
- missing CAB review evidence (`missing_cab_review_evidence.json`)

All are under `tests/fixtures/integrations/servicenow/`.

## Failure behavior matrix
- Unsupported event type → `servicenow_unsupported_event_type`
- Missing required fields / actor identity → `servicenow_missing_required_fields`
- Duplicate deliveries → stable `duplicate_ignored` response (`servicenow_duplicate_delivery`)
- Mapping/payload mismatch → `servicenow_invalid_mapping`
- Policy bundle mismatch/not found → `servicenow_policy_bundle_not_found`
- Other evaluation exceptions → `servicenow_evaluation_error`
