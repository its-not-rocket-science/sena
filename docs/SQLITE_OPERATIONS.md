# SQLite Policy Registry Operations

This runbook covers operational hardening for the policy registry (`src/sena/policy/store.py`) and disaster-recovery workflows.

> Scope note: for supported Jira + ServiceNow incident handling, operators should use integration admin APIs/CLI (completions, dead-letter, replay, manual redrive, duplicate summary) and avoid direct table inspection.

## Durability and concurrency defaults

The SQLite policy registry uses explicit PRAGMA settings on every connection:

- `journal_mode=WAL`: allows concurrent readers while writers commit.
- `synchronous=FULL`: strongest durability posture (calls fsync more aggressively).
- `busy_timeout=5000`: wait up to 5s on transient lock contention.
- `wal_autocheckpoint=1000`: checkpoint WAL periodically to cap WAL growth.
- `temp_store=MEMORY`: reduce temporary-disk churn.

### Tradeoff notes

- `synchronous=FULL` is intentionally conservative for control-plane data where losing committed policy changes is unacceptable.
- If an environment requires lower write latency and accepts a wider crash-loss window, operators may choose `synchronous=NORMAL` only with CAB approval and documented rollback plans.
- WAL mode is preferred for mixed read/write workloads. If running on filesystems with known WAL incompatibilities, switch to `DELETE` mode and accept reduced reader concurrency.


## Schema migration operations

Use explicit migration lifecycle commands before changing registry consumers:

```bash
python -m sena.cli.main registry --sqlite-path /var/lib/sena/policy-registry.db schema-status
python -m sena.cli.main registry --sqlite-path /var/lib/sena/policy-registry.db upgrade --dry-run
python -m sena.cli.main registry --sqlite-path /var/lib/sena/policy-registry.db upgrade
```

Rollback policy is restore-based (forward-only migrations): take a backup before upgrades and restore if rollback is required. See `docs/MIGRATIONS.md` for details.

## Backup cadence

Recommended baseline:

- **Hourly**: SQLite registry backup + manifest.
- **Every release/promotion**: ad-hoc backup before and after active promotion.
- **Daily**: include audit chain file in backup package.
- **Weekly**: full restore drill in non-production using latest backup set.

Command:

```bash
python -m sena.cli.main registry --sqlite-path /var/lib/sena/registry.db \
  backup --output-db /var/backups/sena/registry-$(date +%F-%H%M).db \
  --audit-chain /var/lib/sena/audit/decisions.jsonl
```

## Restore drill procedure

1. Select backup DB, backup manifest, and backup audit-chain artifact.
2. Restore into isolated path.
3. Run verification command and require `status=ok` before cutover.
4. Validate active bundle metadata and history.
5. Record drill evidence (timestamp, operator, artifact hashes, output).

Restore command:

```bash
python -m sena.cli.main registry --sqlite-path /tmp/drill/restored.db \
  restore --backup-db /var/backups/sena/registry-2026-04-02-0100.db \
  --backup-manifest /var/backups/sena/registry-2026-04-02-0100.db.manifest.json \
  --backup-audit /var/backups/sena/registry-2026-04-02-0100.db.audit.jsonl \
  --restore-db /tmp/drill/restored.db \
  --restore-audit /tmp/drill/restored.audit.jsonl
```

Verification command:

```bash
python -m sena.cli.main registry --sqlite-path /tmp/drill/restored.db \
  verify --audit-chain /tmp/drill/restored.audit.jsonl
```

## Failure expectations

- Corrupt snapshots fail with explicit disaster-recovery errors.
- Lock contention surfaces policy-domain conflict errors (`PolicyBundleConflictError`) rather than raw sqlite exceptions.
- Restore verification fails if:
  - `PRAGMA integrity_check` fails,
  - `PRAGMA quick_check` fails,
  - `PRAGMA foreign_key_check` reports violations,
  - any active bundle is missing rules,
  - bundle digest/hash validation fails,
  - single-active-bundle invariant is violated,
  - audit chain validation fails.

## Script equivalents

- `python scripts/backup_policy_registry.py ...`
- `python scripts/restore_policy_registry.py ...`
- `python scripts/verify_policy_registry.py ...`

## Supported integration reliability operations (no direct SQL)

When `SENA_INTEGRATION_RELIABILITY_SQLITE_PATH` is configured, use these commands instead of querying SQLite manually:

```bash
python -m sena.cli.main integrations-reliability --sqlite-path /var/lib/sena/integration-reliability.db completions
python -m sena.cli.main integrations-reliability --sqlite-path /var/lib/sena/integration-reliability.db dead-letter
python -m sena.cli.main integrations-reliability --sqlite-path /var/lib/sena/integration-reliability.db duplicates-summary
python -m sena.cli.main integrations-reliability --sqlite-path /var/lib/sena/integration-reliability.db manual-redrive --id 123 --note "external remediation INC1234"
```
