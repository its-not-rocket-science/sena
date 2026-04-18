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

## 2) Response contract

### A) Same key + same semantic payload

- Returns cached/reused success response (`200`).
- Body is stable for repeated requests with the same key and payload.

### B) Same key + different semantic payload

- Returns `409 Conflict`.
- Error payload is machine-readable with stable reason codes:
  - API idempotency key conflict: `idempotency_key_conflict`
  - Connector delivery-id payload conflict: `delivery_idempotency_payload_conflict`

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
