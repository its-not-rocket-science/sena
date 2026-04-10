# Persistence Architecture

## Why this abstraction exists

SENA ships a SQLite-backed policy registry optimized for local development and alpha use.
The persistence layer intentionally exposes only what is implemented today:

- A repository contract (`PolicyBundleRepository`) that captures bundle lifecycle operations.
- A SQLite adapter (`SQLitePolicyBundleRepository`) that is the only supported backend.
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

SQLite migrations are managed with explicit versions and checksums:

- Migration sources remain in `scripts/migrations/*.sql` with numeric prefixes (`001_...`, `002_...`).
- The `schema_migrations` table stores:
  - `version`
  - `name`
  - `checksum`
  - `applied_at`
- `initialize()` applies only unapplied versions in ascending order.

This model prioritizes deterministic upgrades for the supported SQLite runtime.

## Domain vs persistence models

The persistence layer separates representation concerns:

- **Domain model**: `PolicyRule`, `PolicyBundleMetadata`, and `StoredBundle`.
- **Persistence models**: `BundleRow`, `BundleHistoryRow` used for DB row mapping and write payloads.

This makes it easier to map SQL rows into stable domain objects without leaking schema details into business logic.

## Extension seam (explicitly unsupported by default)

`PolicyBundleRepository` is a narrow protocol seam for internal testing and future adapters.
SENA does **not** currently ship or support any non-SQLite repository implementation.

If a new backend is introduced later, it should only be documented and exported after behavior parity is verified against the repository contract tests.

## Design constraints

- Keep supported (`src/sena/*`) and legacy (`src/sena/legacy/*`) codepaths separate.
- Prefer explicit failure over implicit fallback behavior.
- Avoid overbuilding: only advertise backends that are implemented and tested.
