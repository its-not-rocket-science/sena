# API Idempotency Contract (Supported Path)

This document defines the machine-readable idempotency behavior for supported runtime APIs:

- `POST /v1/evaluate`
- `POST /v1/integrations/webhook`
- `POST /v1/integrations/jira/webhook`
- `POST /v1/integrations/servicenow/webhook`

## 1) Header and scope

- Clients opt into idempotency by sending `Idempotency-Key`.
- Scope is **route + semantic request payload**.
- The key is payload-bound: reusing the same key with a different semantic payload is rejected deterministically.
- Enforcement is **storage-backed** using SQLite atomic claims (not process-local mutex maps), so semantics are consistent across workers/processes sharing the same runtime DB.

## 2) Response contract

### A) Same key + same semantic payload

- Returns cached/reused success response (`200`).
- Body is stable for repeated requests with the same key and payload.
- For concurrent duplicates, one request claims execution and peers wait for completion and replay the completed response.

### B) Same key + different semantic payload

- Returns `409 Conflict`.
- Error payload is machine-readable with stable reason codes:
  - API idempotency key conflict: `idempotency_key_conflict`
  - Connector delivery-id payload conflict: `delivery_idempotency_payload_conflict`

### C) Same key + same payload while original is still running

- The server waits briefly for the in-flight claim to complete.
- If completion is observed, response is replayed as `200`.
- If still not complete within the bounded wait window, request fails with `409` and code `idempotency_key_in_progress`.

## 3) Connector delivery-id behavior (Jira + ServiceNow)

Inbound connector processing also applies delivery-id idempotency:

- Same delivery id + same canonical replay payload: duplicate is ignored safely.
  - Jira duplicate code: `jira_duplicate_delivery`
  - ServiceNow duplicate code: `servicenow_duplicate_delivery`
- Same delivery id + different canonical replay payload: request fails with `409` and reason `delivery_idempotency_payload_conflict`.

Envelope-only differences (for example header ordering, extra non-semantic headers, or raw JSON formatting differences) do not alter semantic payload binding.

## 4) Audit and metrics behavior

- Duplicate and conflict requests do not create duplicate policy decisions.
- Duplicate suppression counters include duplicate deliveries only.
- Inbound idempotency conflict counters are tracked separately (`inbound.conflict_total`) in duplicate-summary surfaces.
