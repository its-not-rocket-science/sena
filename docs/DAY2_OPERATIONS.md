# Day-2 Operations Checklist

This is the practical daily/incident checklist for safe operation.

## Start of shift (safety baseline)

1. Confirm startup controls are still valid:

```bash
python -m sena.cli.main production-check --format json
```

Required: `ok=true`.

2. Confirm process readiness:

```bash
curl -fsS "$SENA_BASE_URL/v1/ready" -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
```

Required: `status=ready`.

3. Snapshot operator overview:

```bash
curl -fsS "$SENA_BASE_URL/v1/operations/overview" -H "x-api-key: $SENA_ADMIN_API_KEY" | jq .
```

Inspect:
- `dead_letters.connector_dead_letter_volume`
- `job_status_counts`
- `outcomes_by_connector_policy_bundle`

## Daily reliability checks

### Dead-letter safety check

```bash
python scripts/dead_letter_admin.py \
  --base-url "$SENA_BASE_URL" \
  --connector jira \
  --api-key "$SENA_ADMIN_API_KEY" \
  list --limit 20
```

If backlog is non-zero:
1. identify root cause,
2. replay only affected IDs,
3. if external remediation already done, use manual redrive with incident note.

### Audit integrity check

```bash
python -m sena.cli.main audit --audit-path "$SENA_AUDIT_CHAIN" verify
```

Required: `valid=true`.

## Promotion safety sequence (candidate -> active)

1. validate gate,
2. promote,
3. verify registry + active bundle.

Commands:

```bash
python -m sena.cli.main registry --sqlite-path "$SENA_REGISTRY_DB" validate-promotion --bundle-id 12 --target-lifecycle active --validation-artifact "CAB-1001"
python -m sena.cli.main registry --sqlite-path "$SENA_REGISTRY_DB" promote --bundle-id 12 --target-lifecycle active --promoted-by sre-oncall --promotion-reason "CAB-1001 approved" --validation-artifact "CAB-1001" --approver-attestation security --approver-attestation platform
python -m sena.cli.main registry --sqlite-path "$SENA_REGISTRY_DB" verify --audit-chain "$SENA_AUDIT_CHAIN"
```

Stop on first non-zero exit code.

## Incident rollback sequence

1. inspect history for last known-good active release,
2. execute rollback,
3. verify active version and audit state.

```bash
python -m sena.cli.main registry --sqlite-path "$SENA_REGISTRY_DB" inspect-history --bundle-name enterprise-compliance-controls
python -m sena.cli.main registry --sqlite-path "$SENA_REGISTRY_DB" rollback --bundle-name enterprise-compliance-controls --to-bundle-id 11 --promoted-by sre-oncall --promotion-reason "INC-4201 mitigation" --validation-artifact "INC-4201"
python -m sena.cli.main registry --sqlite-path "$SENA_REGISTRY_DB" verify --audit-chain "$SENA_AUDIT_CHAIN"
```

## Weekly restore drill (required)

Use the drill helper and keep output JSON as evidence.

```bash
python scripts/registry_backup_restore_drill.py --sqlite-path "$SENA_REGISTRY_DB" --audit-chain "$SENA_AUDIT_CHAIN" --work-dir /tmp/sena-drill
```

Required: final `status=ok`.

## Escalation triggers (act immediately)

- production check returns `ok=false`
- readiness is not `ready`
- audit verify returns `valid=false`
- dead-letter backlog grows for two consecutive checks after replay/manual-redrive
- rollback or restore verification fails

When any trigger occurs, freeze promotions and open incident response.
