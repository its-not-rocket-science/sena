# Audit Durability: Local JSONL Chain, Archives, and Restore Drills

This document covers operational durability for SENA's **local** JSONL audit sink while a future replicated/WORM backend is still on the roadmap.

## Scope

Applies to:
- `JsonlFileAuditSink` (`src/sena/audit/sinks.py`),
- chain verification (`src/sena/audit/chain.py`),
- archive/restore tooling (`src/sena/audit/archive.py`),
- CLI workflows (`python -m sena.cli.main audit ...`).

## Guarantees provided by the local sink (tamper-evident)

When configured with `SENA_AUDIT_SINK_JSONL=/path/to/audit.jsonl`:

1. **Append-oriented writes with locking and fsync**
   - process-level file lock,
   - append-only write path,
   - `fsync` on each append.
2. **Hash-linked chain**
   - each record carries `previous_chain_hash` and `chain_hash`.
3. **Segment rotation support**
   - active file rotates by configured max-bytes policy,
   - rotated inventory stored in `<audit>.manifest.json`.
4. **Deterministic archive packaging**
   - archived segment filenames are deterministic from segment index + sequence range + checksum,
   - archive manifest includes file checksums and chain metadata.
5. **Corruption detection**
   - truncated/garbled JSONL lines,
   - modified segment bytes (checksum mismatch),
   - missing segments,
   - sequence gaps and chain hash inconsistencies.

## Non-guarantees (not WORM, not replicated)

The local sink is **tamper-evident**, not immutable.

It does **not** provide:
- WORM retention lock,
- multi-host replication/quorum durability,
- off-site immutable storage,
- hardware/attestation guarantees for host integrity.

An operator with host-level write permissions can still rewrite files and manifests. Verification increases detection probability, but immutable retention requires external controls.

## Required external controls for stronger assurance

For regulated environments:
- ship archives to immutable object storage,
- enforce bucket/object lock retention policies,
- separate duties: writer vs archive operator vs verifier,
- run periodic restore drills and store verification artifacts.

## CLI workflows

### Verify live chain (active + rotated)

```bash
python -m sena.cli.main audit --audit-path /var/log/sena/audit.jsonl verify
```

### Create deterministic archive bundle

```bash
python -m sena.cli.main audit --audit-path /var/log/sena/audit.jsonl archive \
  --archive-dir /var/backups/sena/audit-archives/2026-04-02
```

### Verify archive manifest + checksums + chain

```bash
python -m sena.cli.main audit --audit-path /var/log/sena/audit.jsonl verify-archive \
  --archive-manifest /var/backups/sena/audit-archives/2026-04-02/audit.jsonl.archive.head-<hash>.manifest.json
```

### Restore archive to drill target and re-verify

```bash
python -m sena.cli.main audit --audit-path /var/log/sena/audit.jsonl restore-archive \
  --archive-manifest /var/backups/sena/audit-archives/2026-04-02/audit.jsonl.archive.head-<hash>.manifest.json \
  --restore-audit-path /tmp/sena-drill/restored.audit.jsonl \
  --verify-after-restore
```

## Example restore drill walkthrough

1. **Capture archive bundle** using `audit archive`.
2. **Persist manifest and archived segments** to your backup target.
3. **Simulate loss** by restoring into a clean directory (`/tmp/sena-drill`).
4. **Run `audit verify-archive`** against archive manifest.
5. **Run `audit restore-archive --verify-after-restore`**.
6. **Record outputs** (JSON results, timestamp, operator) as drill evidence.

Expected success signals:
- `verify-archive.valid=true`,
- `restore.verify.valid=true`,
- restored head hash matches archive manifest head hash.

Expected actionable failures include:
- `missing_archive_segment:<name>`,
- `archive_checksum_mismatch:<name>:expected=...:actual=...`,
- `malformed_record:<file>:<line>`,
- `archive_chain_hash_mismatch:record=<n>:...`.

## Operational interpretation

- **Tamper-evident** means "changes are detectable with verification evidence."
- **WORM/replicated durability** means "changes or loss are prevented/tolerated by storage controls."

SENA's local sink gives the first; you must add external infrastructure for the second.
