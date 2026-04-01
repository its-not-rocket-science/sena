# Persistence Architecture

## Why this abstraction exists

SENA started with a SQLite-backed policy registry optimized for local development and alpha use.
To support enterprise relational storage (PostgreSQL) without rewriting policy lifecycle logic, the persistence layer now has:

- A repository contract (`PolicyBundleRepository`) that captures bundle lifecycle operations.
- A SQLite adapter that is the current production-ready backend.
- A Postgres adapter skeleton that shares the contract and migration expectations.
- Explicit schema migration versioning with checksums for determinism.

## Current guarantees

The SQLite repository guarantees:

1. **Deterministic bundle integrity**
   - Rule content is canonicalized and hashed.
   - Bundle integrity digest is the hash of sorted rule hashes.
2. **Lifecycle safety**
   - Supported transitions are explicit (`draft -> candidate -> active -> deprecated`).
   - Promotion to `active` requires a validation artifact.
   - Lifecycle-changing operations execute inside explicit `BEGIN IMMEDIATE` transactions so writers serialize deterministically.
   - A unique partial index enforces at most one `active` bundle per bundle name.
3. **Complete lifecycle history**
   - Register, promote, auto-deprecate, and rollback transitions are all persisted in `bundle_history`.
4. **Release metadata durability**
   - Release manifest path, signature strictness/result, key id, and verification timestamp are stored in `bundles`.
5. **Startup integrity checks**
   - SQLite `PRAGMA integrity_check` and bundle lifecycle invariants are validated during repository initialization.
6. **Typed repository failures**
   - Conflict, missing bundle, invalid transition, and integrity failures are surfaced with dedicated exception types.

## Schema evolution model

SQLite migrations are now managed with explicit versions and checksums:

- Migration sources remain in `scripts/migrations/*.sql` with numeric prefixes (`001_...`, `002_...`).
- The `schema_migrations` table stores:
  - `version`
  - `name`
  - `checksum`
  - `applied_at`
- `initialize()` applies only unapplied versions in ascending order.

This model is intentionally portable: the same version/checksum metadata can be reused by a future Postgres migrator.

## Domain vs persistence models

The persistence layer separates representation concerns:

- **Domain model**: `PolicyRule`, `PolicyBundleMetadata`, and `StoredBundle`.
- **Persistence models**: `BundleRow`, `BundleHistoryRow` used for DB row mapping and write payloads.

This makes it easier to map backend-specific SQL rows into stable domain objects without leaking schema details into business logic.

## Postgres path

`PostgresPolicyBundleRepository` is added as an adapter skeleton to make the contract concrete for enterprise backends.
It is intentionally not partially functional yet because shipping an untested mixed-mode backend would increase operational risk.

Planned implementation path:

1. Implement shared SQL-friendly repository tests against an adapter fixture.
2. Add Postgres DDL migrations aligned to SQLite schema semantics.
3. Preserve lifecycle and error-semantics parity (transaction boundaries, conflict behavior, invariant checks) in the Postgres implementation.
4. Validate behavior parity via contract tests run on both backends.

## Design constraints

- Keep supported (`src/sena/*`) and legacy (`src/sena/legacy/*`) codepaths separate.
- Prefer explicit failures (`NotImplementedError` for unfinished backend) over silent fallback.
- Avoid overbuilding: SQLite remains the default backend while interfaces and migration scaffolding enable growth.
