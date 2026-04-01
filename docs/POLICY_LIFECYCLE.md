# SENA Policy Lifecycle (Alpha)

This document describes SENA's operator-facing policy lifecycle control-plane capability.

## Lifecycle model

Supported states and transitions:

- `draft -> candidate`
- `candidate -> active`
- `active -> deprecated`
- `rollback` is an explicit controlled action that deprecates current active and re-activates a previous bundle.

Promotion to `active` requires a validation artifact (for example: CI run URL, signed approval record, or change ticket).

## Persisted bundle record

Registry persistence includes:

- Bundle identity (`name`, internal id).
- Release identity (`version`, `release_id`).
- Lifecycle state.
- Creation metadata (`created_at`, `created_by`, `creation_reason`).
- Promotion metadata (`promoted_at`, `promoted_by`, `promotion_reason`).
- Source lineage (`source_bundle_id`).
- Integrity digest (`integrity_digest`).
- Compatibility notes.
- Release notes and migration notes.
- Validation artifact used for active promotion/rollback.

## Operator workflows

### Register

```bash
python -m sena.cli.main registry --sqlite-path /tmp/policy.db register \
  --policy-dir src/sena/examples/policies \
  --bundle-name enterprise-compliance-controls \
  --bundle-version 2026.04.1 \
  --created-by alice \
  --creation-reason "quarterly controls update" \
  --release-notes "new geo block controls" \
  --migration-notes "requires vendor_risk_score fact"
```

### Validate promotion

```bash
python -m sena.cli.main registry --sqlite-path /tmp/policy.db validate-promotion \
  --bundle-id 12 \
  --target-lifecycle active \
  --validation-artifact "https://ci.example/job/123"
```

### Promote

```bash
python -m sena.cli.main registry --sqlite-path /tmp/policy.db promote \
  --bundle-id 12 \
  --target-lifecycle active \
  --promoted-by sre-oncall \
  --promotion-reason "CAB-884 approved" \
  --validation-artifact "CAB-884"
```

### Rollback

```bash
python -m sena.cli.main registry --sqlite-path /tmp/policy.db rollback \
  --bundle-name enterprise-compliance-controls \
  --to-bundle-id 11 \
  --promoted-by sre-oncall \
  --promotion-reason "incident mitigation INC-4201" \
  --validation-artifact "INC-4201"
```

### Inspect history and provenance

```bash
python -m sena.cli.main registry --sqlite-path /tmp/policy.db inspect-history --bundle-name enterprise-compliance-controls
```

History records include what changed (transition), who changed it, why, and which active bundle was replaced.

## API support

Primary endpoints:

- `POST /v1/bundle/register`
- `POST /v1/bundle/promotion/validate`
- `POST /v1/bundle/promote`
- `POST /v1/bundle/rollback`
- `POST /v1/bundle/diff`
- `GET /v1/bundles/active`
- `GET /v1/bundles/{bundle_id}`
- `GET /v1/bundles/by-version`
- `GET /v1/bundles/history`

Payloads are stable JSON structures and invalid transitions return `promotion_validation_failed` with explicit errors.

## Alpha boundaries

Still alpha:

- No cryptographic signing of bundle manifests yet (digest is deterministic but unsigned).
- No multi-step approval workflow engine (artifact is validated for presence, not policy semantics).
- SQLite-first concurrency model (portable schema designed for Postgres migration).
- No row-level tenancy partitioning yet.
