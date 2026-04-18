# SENA Incident Runbooks (Operator-Facing)

This document is the command-first runbook set for failures that block safe operation.

## Global assumptions

```bash
export SENA_BASE_URL="${SENA_BASE_URL:-http://127.0.0.1:8000}"
export SENA_ADMIN_API_KEY="${SENA_ADMIN_API_KEY:?set admin key}"
export SENA_REGISTRY_DB="${SENA_REGISTRY_DB:-/var/lib/sena/policy-registry.db}"
export SENA_AUDIT_CHAIN="${SENA_AUDIT_CHAIN:-/var/lib/sena/audit/decisions.jsonl}"
```

---

## 1) Startup validation failure

### Trigger

Process exits at startup or readiness never becomes healthy.

### Immediate check

```bash
python -m sena.cli.main production-check --format both
```

### Pass criteria

- exit code `0`
- text output starts with `Production readiness check: PASS`
- JSON payload has `"ok": true`

### Failure interpretation

- exit code `1` means one or more startup-fatal controls are missing.
- failed checks appear in `checks[].name` with details in `checks[].details[]`.

### Recovery steps

1. Fix only the listed failing controls.
2. Re-run `production-check` until it passes.
3. Restart SENA and verify readiness:

```bash
curl -fsS "$SENA_BASE_URL/v1/ready" -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
```

Ready response requirement:

- `status` is `ready`
- `checks.policy_bundle_loaded` is `true`
- `checks.auth_config_valid` is `true`

---

## 2) Policy bundle promotion

### Validate promotion gate before state change

```bash
python -m sena.cli.main registry --sqlite-path "$SENA_REGISTRY_DB" validate-promotion \
  --bundle-id 12 \
  --target-lifecycle active \
  --validation-artifact "CAB-1001"
```

Pass criteria:

- JSON includes `"valid": true`.

Failure interpretation:

- validation errors are returned in `errors[]`.
- if invalid, do **not** run `promote`.

### Promote after validation passes

```bash
python -m sena.cli.main registry --sqlite-path "$SENA_REGISTRY_DB" promote \
  --bundle-id 12 \
  --target-lifecycle active \
  --promoted-by sre-oncall \
  --promotion-reason "CAB-1001 approved" \
  --validation-artifact "CAB-1001" \
  --approver-attestation security \
  --approver-attestation platform
```

Post-promotion check:

```bash
python -m sena.cli.main registry --sqlite-path "$SENA_REGISTRY_DB" inspect-history --bundle-name enterprise-compliance-controls
```

Expected: newest history item records the transition and `promotion_reason`.

---

## 3) Rollback to previous active bundle

### Identify rollback target

```bash
python -m sena.cli.main registry --sqlite-path "$SENA_REGISTRY_DB" inspect-history --bundle-name enterprise-compliance-controls
```

Pick the known-good bundle ID from history.

### Execute rollback

```bash
python -m sena.cli.main registry --sqlite-path "$SENA_REGISTRY_DB" rollback \
  --bundle-name enterprise-compliance-controls \
  --to-bundle-id 11 \
  --promoted-by sre-oncall \
  --promotion-reason "INC-4201 mitigation" \
  --validation-artifact "INC-4201"
```

Post-rollback checks:

```bash
python -m sena.cli.main registry --sqlite-path "$SENA_REGISTRY_DB" verify --audit-chain "$SENA_AUDIT_CHAIN"
curl -fsS "$SENA_BASE_URL/v1/bundles/active" -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
```

Expected:

- verification status `ok`
- active bundle version matches rollback target.

---

## 4) Audit verification failure

### Verify and capture diagnostics

```bash
python -m sena.cli.main audit --audit-path "$SENA_AUDIT_CHAIN" verify
```

Pass criteria: output has `"valid": true`.

Failure interpretation:

- `"valid": false` means audit evidence is untrusted until fixed.
- use `diagnostics[].category` + `diagnostics[].location` to identify first damaged segment/record.

### Remediation sequence

1. Stop write traffic.
2. Preserve forensic copy of current audit files.
3. Restore missing/corrupt files from backup.
4. Re-run verify command until `valid=true`.

---

## 5) Dead-letter replay / manual redrive

Use API directly or helper script.

### List dead-letter records

```bash
python scripts/dead_letter_admin.py \
  --base-url "$SENA_BASE_URL" \
  --connector jira \
  --api-key "$SENA_ADMIN_API_KEY" \
  list --limit 20
```

Expected response path: `response.items[]` with `id`, `operation_key`, `attempts`, `reason`.

### Replay specific records

```bash
python scripts/dead_letter_admin.py \
  --base-url "$SENA_BASE_URL" \
  --connector jira \
  --api-key "$SENA_ADMIN_API_KEY" \
  replay --ids 101 102
```

Interpretation:

- `response.succeeded` > 0: replay accepted.
- `response.failed` > 0: replay attempted but downstream still failing.
- `response.not_found` > 0: ID already cleared or invalid.

### Manual redrive when replay is not safe

```bash
python scripts/dead_letter_admin.py \
  --base-url "$SENA_BASE_URL" \
  --connector jira \
  --api-key "$SENA_ADMIN_API_KEY" \
  manual-redrive --ids 103 --note "external fix INC-777"
```

Interpretation:

- records move from dead-letter to completion log with `status=manually_redriven`.

---

## 6) Backup / restore verification

### Single-command drill (new helper)

Dry-run:

```bash
python scripts/registry_backup_restore_drill.py \
  --sqlite-path "$SENA_REGISTRY_DB" \
  --audit-chain "$SENA_AUDIT_CHAIN" \
  --work-dir /tmp/sena-drill \
  --dry-run
```

Execute:

```bash
python scripts/registry_backup_restore_drill.py \
  --sqlite-path "$SENA_REGISTRY_DB" \
  --audit-chain "$SENA_AUDIT_CHAIN" \
  --work-dir /tmp/sena-drill
```

Pass criteria:

- script exits `0`
- final JSON has `"status": "ok"`
- verify step output includes `"status": "ok"`

Failure interpretation:

- final JSON has `status=failed` and includes per-step `exit_code`, `stdout`, `stderr`.
- most common root causes: corrupt backup, missing audit file, integrity/digest mismatch, signature verification failure when strict options are provided.
