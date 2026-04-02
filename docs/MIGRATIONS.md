# Policy Registry Migrations

This document defines the **versioned SQLite schema migration workflow** for the policy registry.

## Migration model

- Migration SQL files live in `scripts/migrations/`.
- File naming is `<NNN>_<description>.sql` (for example: `001_policy_registry.sql`).
- Versions must be contiguous from `1..N`; startup fails if there are gaps or duplicates.
- Applied migrations are recorded in `schema_migrations` with:
  - `version`
  - `name`
  - `checksum` (SHA-256 of SQL content)
  - `applied_at` (UTC ISO timestamp)

## Safety guarantees

- **Ordered upgrades:** migrations always run in ascending version order.
- **Checksum validation:** previously applied migrations are validated against current file checksums before planning/apply.
- **Idempotent reruns:** already-applied versions are skipped.
- **Step-level transaction boundaries:** each migration version is applied atomically; on failure, that version is rolled back and later versions are not attempted.

## Commands

### Inspect current schema state

```bash
python -m sena.cli.main registry --sqlite-path /var/lib/sena/policy-registry.db schema-status
```

Example output fields:

- `current_version`
- `latest_available_version`
- `pending_versions`
- `applied` (version/name/checksum/applied_at)

### Dry-run an upgrade

```bash
python -m sena.cli.main registry --sqlite-path /var/lib/sena/policy-registry.db \
  upgrade --dry-run
```

Optional target:

```bash
python -m sena.cli.main registry --sqlite-path /var/lib/sena/policy-registry.db \
  upgrade --dry-run --target-version 5
```

### Apply upgrades

```bash
python -m sena.cli.main registry --sqlite-path /var/lib/sena/policy-registry.db upgrade
```

Optional target:

```bash
python -m sena.cli.main registry --sqlite-path /var/lib/sena/policy-registry.db \
  upgrade --target-version 5
```

## Scripted operator entrypoint

Equivalent script interface:

```bash
python scripts/migrate_policy_registry.py --sqlite-path /var/lib/sena/policy-registry.db --dry-run
python scripts/migrate_policy_registry.py --sqlite-path /var/lib/sena/policy-registry.db
python scripts/migrate_policy_registry.py --sqlite-path /var/lib/sena/policy-registry.db --inspect-only
```

## Rollback policy (explicit)

SENA currently supports **forward-only schema migrations** (no automatic down migrations).

Rollback is **restore-based**:

1. Take a pre-upgrade backup (`registry backup`).
2. Apply schema upgrades.
3. If rollback is required, restore the last known-good backup (`registry restore`).
4. Verify the restored state (`registry verify`).

This policy is intentional for deterministic operations and reduced risk from partially maintained down migrations.

## Recommended production procedure

1. `registry backup`
2. `registry upgrade --dry-run`
3. `registry upgrade`
4. `registry schema-status`
5. `registry verify`

Store command output in release evidence.
