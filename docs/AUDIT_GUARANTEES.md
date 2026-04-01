# SENA Audit Guarantees and Limits

This document describes what SENA's built-in local-file audit subsystem **does** and **does not** guarantee.

## What SENA now guarantees (local node scope)

When `SENA_AUDIT_SINK_JSONL` is configured to a local path:

1. **Append-focused writes with writer coordination**
   - SENA writes records with explicit process-level file locking.
   - Writes use append mode with fsync to reduce loss during crashes.
2. **Tamper-evident hash chain**
   - Every record includes `previous_chain_hash` and `chain_hash`.
   - Chain verification detects hash mismatches and link breaks.
3. **Durability metadata per record**
   - Records include: `event_type`, `source_metadata`, `request_correlation_id`,
     `evaluator_version`, `policy_bundle_release_id`, `write_timestamp`, and optional
     `storage_sequence_number`.
4. **Rotation support and segment index**
   - Rotated files are tracked in a manifest (`<audit>.manifest.json`) that records
     segment inventory and summary metadata.
5. **Operational verification reporting**
   - Verification reports malformed records, missing segments, sequence gaps,
     and inconsistent chain links.

## What SENA does not guarantee by itself

SENA local files are **not** a compliance archive on their own.

- No immutable WORM guarantee.
- No cross-host replication or quorum durability.
- No automatic off-site retention.
- No hardware-backed attestation of host integrity.

A privileged host operator can still delete or replace files, including the manifest.
Hash verification will expose many forms of tampering, but immutable retention requires
external controls.

## Required external controls for stronger assurance

For regulated workloads, pair SENA with:

- WORM-capable object storage or immutable snapshots.
- Centralized log shipping with retention lock.
- Backup/restore exercises that include `GET /v1/audit/verify` checks.
- Separation of duties for operators who can write vs. verify vs. retain artifacts.

## Verification workflow

1. Run API verification endpoint (`GET /v1/audit/verify`) or CLI verify mode.
2. Treat any `valid=false` result as an incident requiring triage.
3. Inspect errors for:
   - `missing_segment:*`
   - `malformed_record:*`
   - `previous_chain_hash mismatch`
   - `chain_hash mismatch`
   - `storage sequence gap`
4. Preserve current files before remediation; do not overwrite forensic artifacts.
