# Tenancy model

SENA runtime payload governance uses an explicit **tenant + region** partitioning model.

## Partition key

Every governed payload is keyed by:

- `tenant_id` (logical tenant boundary)
- `region` (data residency boundary)

Storage and retrieval are scoped to this pair. A query for one tenant/region cannot return data from a different region.

## Region pinning

- Requests may provide `region` directly, or via request `facts.region`.
- If missing, SENA uses `SENA_DATA_DEFAULT_REGION`.
- Region must be in `SENA_DATA_ALLOWED_REGIONS`; otherwise request processing fails explicitly.

## Governed payload lifecycle

- Incoming evaluate/webhook payloads are scanned for PII patterns.
- A redacted payload plus PII field flags are persisted in `governed_payloads`.
- TTL is controlled by `SENA_PAYLOAD_RETENTION_TTL_HOURS`.
- Expired payloads are purged, except records under legal hold.

## Legal hold

Legal hold is supported for governed payload rows through:

- `POST /v1/admin/data/payloads/{payload_id}/hold`

Held rows are excluded from retention purge.

## Access audit

All governed data access operations are written to `data_access_events`:

- reads
- writes
- retention purge actions
- legal hold actions

Use `GET /v1/admin/data-access` for event retrieval.
