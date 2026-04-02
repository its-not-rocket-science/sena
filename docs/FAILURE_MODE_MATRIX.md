# Failure Mode Matrix (Deterministic Governance)

This matrix tracks how SENA behaves under expected failure classes for deterministic governance.

## Defaults and policy stance

Where behavior could be interpreted multiple ways, SENA uses **fail-closed** defaults:

- unknown/malformed integration mappings are rejected (no implicit allow),
- invalid lifecycle and rollback transitions are rejected,
- malformed replay inputs are rejected,
- strict startup checks fail process startup when required controls are missing.

All API failures are expected to return machine-readable envelopes:

```json
{
  "error": {
    "code": "stable_error_code",
    "message": "stable message",
    "request_id": "req_...",
    "timestamp": "RFC3339",
    "details": {"...": "..."}
  }
}
```

## Matrix

| Failure mode | Surface | Fail-closed behavior | Error code(s) / signal | Status |
|---|---|---|---|---|
| Malformed policy bundles | parser/startup/register | Reject bundle load/registration | `PolicyParseError`, startup `RuntimeError` | **Tested** |
| Invalid lifecycle transitions | lifecycle + `/v1/bundle/promote` | Reject transition | `promotion_validation_failed` + transition details | **Tested** |
| Malformed webhook mappings (config + event mapping) | mapping loader + `/v1/integrations/webhook` | Reject config/event; do not evaluate | `webhook_mapping_error` | **Tested** |
| Oversized payloads | API middleware | Reject request before route execution | `payload_too_large` | **Tested** |
| Request timeout behavior | API middleware | Abort request; no partial success payload | `timeout` | **Tested** |
| Replay drift edge cases | replay loader | Reject malformed replay inputs | `ReplayInputError` | **Tested** |
| Idempotency / retry behavior | Jira/ServiceNow/webhook deliveries + promotion idempotency | Duplicate deliveries return deterministic duplicate response; repeat same-state promotion stays idempotent | `jira_duplicate_delivery`, `servicenow_duplicate_delivery`, `idempotent=true` | **Tested** |
| Promotion rollback failures | `/v1/bundle/rollback` | Reject invalid rollback targets/transitions | `promotion_validation_failed` + stable detail message | **Tested** |
| Audit verification failures | startup + `/v1/audit/verify` | Report tamper/corruption; optional strict startup block | `valid=false` with verification errors; strict startup `RuntimeError` | **Tested** |
| Startup validation failures | app startup/runtime config | Fail startup if required controls are missing/invalid | `RuntimeError` with explicit setting constraint | **Tested** |
| Connector outbound delivery failures | Jira/ServiceNow outbound transport | Surface deterministic transport error contract | currently mapped as integration-specific runtime errors | **Not yet fully tested** |
| Backpressure/lock contention under concurrent promotion load | sqlite store | deterministic conflict/retry semantics | `PolicyBundleConflictError` | **Not yet fully tested** |

## Notes on determinism

- Error **codes** should be treated as primary machine contract.
- `details` fields may include contextual values but should preserve stable keys for automation.
- Duplicate-delivery responses are treated as non-fatal idempotent acknowledgements and keep machine-readable `error` objects.
