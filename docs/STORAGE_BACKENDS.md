# Storage Backends Contract

This document defines SENA persistence boundaries and backend expectations.

## Persistence concerns

SENA runtime state is split into explicit concerns:

1. **Audit sink** (`sena.audit.storage.AuditStorage`)
2. **Policy bundle store** (`sena.policy.store.PolicyBundleRepository`)
3. **Integration reliability/idempotency store** (`sena.integrations.persistence.IntegrationReliabilityStore`)
4. **Runtime processing state store** (`sena.api.processing_store.RuntimeStateStore`)
5. **Ingestion queue backend** (`sena.services.reliability_service.IngestionQueueBackend`)

## Capability model

Each backend advertises capability metadata in `sena.storage_backends.CAPABILITIES`:

- `concurrency_model`
- `durability_assumptions`
- `deployment_suitability` (`local_dev`, `pilot`, `production`)
- operational notes

Startup validation now inspects these profiles.

- In `production` mode:
  - **local_dev** backends fail startup.
  - **pilot** backends emit explicit warnings during startup.

## Backend naming and readiness labels

To reduce ambiguity, local implementations are explicitly named:

- `DevelopmentJsonlAuditStorage` (compat alias: `LocalFileStorage`)
- `PilotSQLiteAppendOnlyAuditStorage` (compat alias: `SQLiteAppendOnlyStorage`)
- `PilotSQLiteIntegrationReliabilityStore` (compat alias: `SQLiteIntegrationReliabilityStore`)

These aliases preserve backwards compatibility while making readiness explicit.

## Production backend guarantees

A production-intended backend must guarantee:

1. **Crash durability**: acknowledged writes survive process/node crash.
2. **Concurrency safety**: well-defined behavior across multiple workers/instances.
3. **Tamper evidence / immutability** for audit trails.
4. **Operational recoverability**: backups, restore, and integrity validation.
5. **Deterministic failure semantics**: explicit errors instead of silent fallback.

For audit specifically, production backends should provide immutable retention controls (for example, object lock / immutable blob policies) and externally verifiable retention posture.

## Validation behavior

Storage safety is enforced at startup (`sena.api.runtime.validate_startup_settings`) and in production readiness checks (`sena.api.production_check.run_production_readiness_check`).

This ensures operators receive clear guidance when using pilot/local storage selections in production deployments.
