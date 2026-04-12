# Jira Integration Runbook

## Scope
This is a **supported** deterministic Jira approval gateway. Jira issue webhooks are normalized into `ActionProposal`, evaluated by policy bundles, and returned as machine-readable decisions (with optional outbound Jira payloads).

It is not a Jira workflow-engine replacement; unsupported events and malformed payloads fail closed.

## Supported flow
1. Jira sends webhook to `POST /v1/integrations/jira/webhook`.
2. SENA verifies authenticity with a pluggable verifier contract.
3. SENA validates and normalizes payload using a strict route mapping.
4. SENA evaluates mapped `ActionProposal` against active policy bundle.
5. SENA returns machine-readable result and optionally sends outbound Jira decision payloads.

## Webhook headers and signature formats (supported)
### Delivery identity headers
- Preferred: `x-atlassian-webhook-identifier`
- Fallback: `x-request-id`
- Final fallback if neither header is present: deterministic synthetic key `"{event_type}:{timestamp}:{issue.id}"`.

### Signature headers and accepted formats
When `SENA_JIRA_WEBHOOK_SECRET` is configured, signatures are required and verified as HMAC-SHA256 over the raw request body.

- Primary header: `x-sena-signature`
  - Format: lowercase/uppercase hex digest value (no prefix).
- Alternate header: `x-hub-signature-256`
  - Format A: `sha256=<hex_digest>`
  - Format B: `<hex_digest>` (unprefixed)

If neither header is present while a secret is configured, SENA returns `401 jira_authentication_failed` with `signature_error=missing_signature`.
If present but incorrect, SENA returns `401 jira_authentication_failed` with `signature_error=invalid_signature`.

### Test-backed examples
- Current + previous secret acceptance: `tests/test_api.py::test_jira_webhook_signature_verification_accepts_current_and_previous_secret`
- Unprefixed `x-hub-signature-256` acceptance: `tests/test_api.py::test_jira_webhook_signature_verification_accepts_unprefixed_x_hub_signature_256`
- Missing/invalid signature rejection:
  - `tests/test_api.py::test_jira_webhook_signature_verification_rejects_missing_signature_when_secret_configured`
  - `tests/test_api.py::test_jira_webhook_signature_verification_rejects_invalid_signature`

## Configuration
Set:

```bash
export SENA_JIRA_MAPPING_CONFIG=src/sena/examples/integrations/jira_mappings.yaml
export SENA_JIRA_WEBHOOK_SECRET=local-dev-secret  # optional in local dev
```

Example mapping file: `src/sena/examples/integrations/jira_mappings.yaml`.

## Release/readiness confidence artifact
The authoritative, machine-generated confidence matrix (supported event types, signature verification modes, duplicate behavior, required metadata/field failures, and known unsupported cases) is published at `docs/artifacts/integrations/jira_servicenow_confidence_matrix.json`.

It is generated from committed mappings (`src/sena/examples/integrations/*_mappings.yaml`), committed fixtures, and test-backed assertions in `tests/fixtures/integrations/confidence_assertions.json`, and CI fails on drift via `scripts/generate_integration_confidence_matrix.py --check`.

## Local test scenario
```bash
curl -X POST http://127.0.0.1:8000/v1/integrations/jira/webhook \
  -H 'Content-Type: application/json' \
  -H 'x-atlassian-webhook-identifier: jira-dev-1' \
  -d '{
    "webhookEvent": "jira:issue_updated",
    "issue": {
      "id": "10001",
      "key": "RISK-9",
      "fields": {
        "customfield_approval_amount": 25000,
        "customfield_requester_role": "finance_analyst",
        "customfield_vendor_verified": false
      }
    },
    "user": {"accountId": "acct-99"},
    "changelog": {"items": [{"field": "status", "toString": "Pending Approval"}]}
  }'
```

## Example policy rules for Jira approvals
Use existing payment rules and map Jira fields:
- `customfield_approval_amount` -> `amount`
- `customfield_vendor_verified` -> `vendor_verified`
- `customfield_requester_role` -> `requester_role`

This lets `approve_vendor_payment` rules evaluate Jira-native approval requests deterministically.

## Deployment notes
- Configure `SENA_INTEGRATION_RELIABILITY_SQLITE_PATH` to persist Jira idempotency + outbound delivery bookkeeping.
- In production mode, Jira integration startup fails unless durable reliability storage is explicitly configured.
- In-memory connector reliability is development/demo-only (`SENA_INTEGRATION_RELIABILITY_ALLOW_INMEMORY=true`).
- Pin Jira webhook routes to explicit event types and required fields.

## Duplicate delivery behavior
- Inbound duplicates are suppressed by delivery-id idempotency and return deterministic API payload:
  - HTTP `200`
  - Top-level `status=duplicate_ignored`
  - Error code `jira_duplicate_delivery`
- Outbound duplicates are suppressed by operation key (`decision_id + target + issue_key`) and reported in duplicate counters.
- Test-backed evidence:
  - Inbound duplicate handling: `tests/test_api.py::test_jira_webhook_duplicate_delivery_returns_stable_duplicate_response`
  - Outbound duplicate suppression: `tests/test_jira_integration.py::test_jira_send_decision_is_idempotent_for_retries`

## Outbound reliability operator commands
- List outbound completion records:
  - API: `GET /v1/integrations/jira/admin/outbound/completions?limit=100`
  - CLI: `python -m sena.cli.main integrations-reliability --sqlite-path <reliability.db> completions`
- List outbound dead-letter records:
  - API: `GET /v1/integrations/jira/admin/outbound/dead-letter?limit=100`
  - CLI: `python -m sena.cli.main integrations-reliability --sqlite-path <reliability.db> dead-letter`
- Replay dead-letter records through configured Jira outbound client:
  - API: `POST /v1/integrations/jira/admin/outbound/dead-letter/replay` with JSON body `[<dead_letter_id>, ...]`
- Manually mark dead-letter records as redriven after external operator action:
  - API: `POST /v1/integrations/jira/admin/outbound/dead-letter/manual-redrive?note=<note>` with JSON body `[<dead_letter_id>, ...]`
  - CLI: `python -m sena.cli.main integrations-reliability --sqlite-path <reliability.db> manual-redrive --id <dead_letter_id> --note "<note>"`
- Summarize duplicate suppression counters:
  - API: `GET /v1/integrations/jira/admin/outbound/duplicates/summary`
  - CLI: `python -m sena.cli.main integrations-reliability --sqlite-path <reliability.db> duplicates-summary`
- Summarize outbound reliability counters (delivery attempts, failures, replay/manual-redrive activity):
  - API: `GET /v1/integrations/jira/admin/outbound/reliability/summary`
- Keep bundle naming aligned with route `policy_bundle` values.

## Write-back semantics
Jira write-back is controlled by mapping `outbound.mode`:
- `comment`: publish comment only
- `status`: publish status payload only
- `both`: publish both comment and status (default in example mapping)
- `none`: no outbound write-back

Outcomes:
- success for all configured targets: `status=delivered`
- at least one target exhausted retries: `status=partial_failure` with per-target errors; failed deliveries are dead-lettered for replay/manual-redrive.
- Test-backed evidence:
  - Stable successful send: `tests/test_jira_integration.py::test_jira_send_decision_returns_stable_payload`
  - Retry-exhaustion + DLQ behavior: `tests/test_jira_integration.py::test_jira_send_decision_writes_dlq_after_retry_exhaustion`

## Supported-path incident flow (copy/paste)

```bash
export SENA_BASE_URL="${SENA_BASE_URL:-http://127.0.0.1:8000}"
export SENA_ADMIN_API_KEY="${SENA_ADMIN_API_KEY:?set admin key}"
```

1) Inspect successful outbound completions:

```bash
curl -fsS "$SENA_BASE_URL/v1/integrations/jira/admin/outbound/completions?limit=25" \
  -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
```

2) Inspect dead-letter records:

```bash
curl -fsS "$SENA_BASE_URL/v1/integrations/jira/admin/outbound/dead-letter?limit=25" \
  -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
```

3) Replay one dead-letter record after root cause fix:

```bash
curl -fsS -X POST "$SENA_BASE_URL/v1/integrations/jira/admin/outbound/dead-letter/replay" \
  -H "x-api-key: $SENA_ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '[123]' | jq .
```

4) Manual redrive (external remediation already done):

```bash
curl -fsS -X POST "$SENA_BASE_URL/v1/integrations/jira/admin/outbound/dead-letter/manual-redrive?note=external-remediation-INC1234" \
  -H "x-api-key: $SENA_ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '[123]' | jq .
```

5) Interpret duplicate suppression:

```bash
curl -fsS "$SENA_BASE_URL/v1/integrations/jira/admin/outbound/duplicates/summary" \
  -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
```

- `inbound.suppressed_total`: duplicate Jira webhook deliveries ignored safely.
- `outbound.suppressed_total`: duplicate comment/status sends prevented.
- `outbound.by_target.comment|status`: isolate repeated suppression by delivery type.
