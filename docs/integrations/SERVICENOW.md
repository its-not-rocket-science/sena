# ServiceNow Integration Runbook

## Scope
This is a **supported** integration for high-risk, auditable ServiceNow change approvals. It converts ServiceNow approval requests into normalized `ActionProposal` objects and returns deterministic callback payloads for Flow Designer or Business Rules.

## Supported flow
1. ServiceNow sends a change-approval event to `POST /v1/integrations/servicenow/webhook`.
2. SENA normalizes the request into a shared `NormalizedApprovalEvent` model used by both Jira and ServiceNow connectors.
3. SENA maps that event to `ActionProposal` and evaluates policies.
4. SENA returns a deterministic decision response and a callback payload shape suitable for source workflow consumption.

## Configuration
```bash
export SENA_SERVICENOW_MAPPING_CONFIG=src/sena/examples/integrations/servicenow_mappings.yaml
```

## Webhook headers and signature formats (supported)
### Delivery identity headers
- Preferred: `x-servicenow-delivery-id`
- Fallback: `x-request-id`
- Final fallback if neither header is present: deterministic synthetic key `"{event_type}:{source_record_id}:{updated_at|sys_updated_on|na}"`.

### Signature headers and accepted formats
When `SENA_SERVICENOW_WEBHOOK_SECRET` is configured, signatures are required and verified as HMAC-SHA256 over the raw request body.

- Primary header: `x-sena-signature`
  - Format: lowercase/uppercase hex digest value (no prefix).
- Alternate header: `x-servicenow-signature`
  - Format A: `sha256=<hex_digest>`
  - Format B: `<hex_digest>` (unprefixed)

If neither header is present while a secret is configured, SENA returns `401 servicenow_authentication_failed` with `signature_error=missing_signature`.
If present but incorrect, SENA returns `401 servicenow_authentication_failed` with `signature_error=invalid_signature`.

### Test-backed examples
- Current + previous secret acceptance: `tests/test_api.py::test_servicenow_webhook_signature_verification_accepts_current_and_previous_secret`
- Unprefixed `x-servicenow-signature` acceptance: `tests/test_api.py::test_servicenow_webhook_signature_verification_accepts_unprefixed_x_servicenow_signature`
- Missing/invalid signature rejection:
  - `tests/test_api.py::test_servicenow_webhook_signature_verification_rejects_missing_signature_when_secret_configured`
  - `tests/test_api.py::test_servicenow_webhook_signature_verification_rejects_invalid_signature`

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

## Release/readiness confidence artifact
The authoritative, machine-generated confidence matrix (supported event types, signature verification modes, duplicate behavior, required metadata/field failures, and known unsupported cases) is published at `docs/artifacts/integrations/jira_servicenow_confidence_matrix.json`.

It is generated from committed mappings (`src/sena/examples/integrations/*_mappings.yaml`), committed fixtures, and test-backed assertions in `tests/fixtures/integrations/confidence_assertions.json`, and CI fails on drift via `scripts/generate_integration_confidence_matrix.py --check`.

## Reliability storage requirements
- Configure `SENA_INTEGRATION_RELIABILITY_SQLITE_PATH` to persist duplicate-suppression and outbound retry/dead-letter state.
- In production mode, ServiceNow integration startup fails unless durable reliability storage is explicitly configured.
- In-memory reliability mode is for explicit development/demo usage only (`SENA_INTEGRATION_RELIABILITY_ALLOW_INMEMORY=true`).

## Duplicate delivery behavior
- Inbound duplicates are suppressed by delivery-id idempotency and return deterministic API payload:
  - HTTP `200`
  - Top-level `status=duplicate_ignored`
  - Error code `servicenow_duplicate_delivery`
- Outbound duplicates are suppressed by operation key (`decision_id + callback + request_id`) and reported in duplicate counters.
- Test-backed evidence:
  - Inbound duplicate handling: `tests/test_api.py::test_servicenow_webhook_duplicate_delivery_returns_stable_duplicate_response`
  - Outbound duplicate suppression: `tests/test_servicenow_integration.py::test_servicenow_send_decision_is_idempotent_for_duplicate_retry`

## Outbound reliability operator commands
- List outbound completion records:
  - API: `GET /v1/integrations/servicenow/admin/outbound/completions?limit=100`
  - CLI: `python -m sena.cli.main integrations-reliability --sqlite-path <reliability.db> completions`
- List outbound dead-letter records:
  - API: `GET /v1/integrations/servicenow/admin/outbound/dead-letter?limit=100`
  - CLI: `python -m sena.cli.main integrations-reliability --sqlite-path <reliability.db> dead-letter`
- Replay dead-letter records through configured ServiceNow callback client:
  - API: `POST /v1/integrations/servicenow/admin/outbound/dead-letter/replay` with JSON body `[<dead_letter_id>, ...]`
- Manually mark dead-letter records as redriven after operator remediation:
  - API: `POST /v1/integrations/servicenow/admin/outbound/dead-letter/manual-redrive?note=<note>` with JSON body `[<dead_letter_id>, ...]`
  - CLI: `python -m sena.cli.main integrations-reliability --sqlite-path <reliability.db> manual-redrive --id <dead_letter_id> --note "<note>"`
- Summarize duplicate suppression counters:
  - API: `GET /v1/integrations/servicenow/admin/outbound/duplicates/summary`
  - CLI: `python -m sena.cli.main integrations-reliability --sqlite-path <reliability.db> duplicates-summary`
- Summarize outbound reliability counters (delivery attempts, failures, replay/manual-redrive activity):
  - API: `GET /v1/integrations/servicenow/admin/outbound/reliability/summary`

## Supported-path incident flow (copy/paste)

```bash
export SENA_BASE_URL="${SENA_BASE_URL:-http://127.0.0.1:8000}"
export SENA_ADMIN_API_KEY="${SENA_ADMIN_API_KEY:?set admin key}"
```

1) Inspect successful outbound completions:

```bash
curl -fsS "$SENA_BASE_URL/v1/integrations/servicenow/admin/outbound/completions?limit=25" \
  -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
```

2) Inspect dead-letter records:

```bash
curl -fsS "$SENA_BASE_URL/v1/integrations/servicenow/admin/outbound/dead-letter?limit=25" \
  -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
```

3) Replay one dead-letter record after root cause fix:

```bash
curl -fsS -X POST "$SENA_BASE_URL/v1/integrations/servicenow/admin/outbound/dead-letter/replay" \
  -H "x-api-key: $SENA_ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '[123]' | jq .
```

4) Manual redrive (external remediation already done):

```bash
curl -fsS -X POST "$SENA_BASE_URL/v1/integrations/servicenow/admin/outbound/dead-letter/manual-redrive?note=external-remediation-INC1234" \
  -H "x-api-key: $SENA_ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '[123]' | jq .
```

5) Interpret duplicate suppression:

```bash
curl -fsS "$SENA_BASE_URL/v1/integrations/servicenow/admin/outbound/duplicates/summary" \
  -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
```

- `inbound.suppressed_total`: duplicate ServiceNow webhook deliveries ignored safely.
- `outbound.suppressed_total`: duplicate callback sends prevented.
- `outbound.by_target.callback`: suppression concentration for callback channel.

## Write-back semantics
ServiceNow write-back is callback-oriented and controlled by mapping `outbound.mode`:
- `callback`: publish deterministic callback payload to configured callback client
- `none`: no outbound callback write-back

Outcomes:
- successful callback delivery: `status=delivered`
- retries exhausted: `status=delivery_failed` and payload is retained for replay/manual-redrive via outbound dead-letter records.
- Test-backed evidence:
  - Deterministic callback payload shape: `tests/test_servicenow_integration.py::test_servicenow_send_decision_returns_deterministic_callback_shape`
  - Retry-exhaustion + DLQ behavior: `tests/test_servicenow_integration.py::test_servicenow_send_decision_writes_dlq_after_retry_exhaustion`
