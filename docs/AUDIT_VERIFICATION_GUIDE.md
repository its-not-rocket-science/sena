# Audit verification guide (operator quick reference)

Use this runbook when a SENA audit chain must be validated after backup restore, incident response, or suspected tampering.

## 1) Run verification

```bash
python -m sena.cli.main audit --audit-path /var/lib/sena/audit.jsonl verify
```

- `valid=true` means chain/link integrity checks passed.
- `valid=false` means fail-closed: do **not** trust downstream evidence until remediated.

## 2) Read diagnostics

`verify` now returns both:
- `errors`: compact human-readable strings.
- `diagnostics`: structured details for automation.

Each diagnostic includes:
- `category` (stable failure class)
- `location` (segment/file location such as `audit.jsonl.seg-000001.jsonl#4`)
- `record_index` (when applicable)
- `message` (what failed)
- `remediation` (operator next step)

Common categories:
- `chain_link_mismatch`, `chain_hash_mismatch`
- `duplicate_decision_id`, `duplicate_storage_sequence_number`, `storage_sequence_gap`
- `segment_sequence_gap`, `manifest_segment_record_count_mismatch`, `manifest_next_sequence_mismatch`
- `record_malformed_json`, `manifest_segment_missing`, `orphaned_segment_file`
- `signature_present_but_no_verifier`, `signature_verification_failed`

## 3) Typical remediation workflow

1. Freeze write traffic to the affected environment.
2. Save a forensic copy of audit files + manifest before any recovery.
3. Follow `location` and `category` to identify first failing segment/record.
4. Restore missing/corrupted files from immutable backup.
5. Re-run verification until `valid=true`.
6. Resume ingestion only after verification passes.

## 4) Generate synthetic tamper fixtures (for drills)

Use the helper script to produce deterministic attack fixtures:

```bash
python scripts/generate_audit_tamper_fixture.py \
  --case sequence_gap_rotated \
  --output-dir /tmp/sena-audit-drill
```

Supported `--case` values:
`record_deletion`, `record_reordering`, `duplicate_decision_id`,
`sequence_gap_rotated`, `recomputed_hash_tamper`,
`manifest_segment_divergence`, `signature_without_verifier`, `truncated_jsonl`.

Then run:

```bash
python -m sena.cli.main audit --audit-path /tmp/sena-audit-drill/audit.jsonl verify
```
