# SENA Credible Pilot Profile (Opinionated)

This is the supported narrow pilot profile for teams that need trustworthy operation without broad configurability.

## Scope and intended use

- Single tenant, or tightly controlled tenant boundary operated by one platform/security team.
- Inbound integrations: **Jira + ServiceNow only**.
- Deterministic policy decisions from signed, versioned bundles.
- Replayable evidence via durable audit artifacts.

## Exact environment requirements

Set all of the following:

```bash
export SENA_DEPLOYMENT_PROFILE=credible_pilot
export SENA_RUNTIME_MODE=pilot
export SENA_API_KEY_ENABLED=true
export SENA_API_KEYS="author-key:policy_author,review-key:reviewer,deploy-key:deployer,audit-key:auditor,admin-key:admin"

export SENA_POLICY_STORE_BACKEND=sqlite
export SENA_POLICY_STORE_SQLITE_PATH=/var/lib/sena/policy_registry.db

export SENA_INGESTION_QUEUE_BACKEND=sqlite
export SENA_PROCESSING_SQLITE_PATH=/var/lib/sena/runtime.db
export SENA_INTEGRATION_RELIABILITY_SQLITE_PATH=/var/lib/sena/integration_reliability.db
export SENA_INTEGRATION_RELIABILITY_ALLOW_INMEMORY=false

export SENA_AUDIT_SINK_JSONL=/var/log/sena/audit.jsonl
export SENA_AUDIT_VERIFY_ON_STARTUP_STRICT=true

export SENA_BUNDLE_SIGNATURE_STRICT=true
export SENA_BUNDLE_SIGNATURE_KEYRING_DIR=/etc/sena/keyring

export SENA_JIRA_MAPPING_CONFIG=/etc/sena/integrations/jira.yaml
export SENA_JIRA_WEBHOOK_SECRET='replace-with-secret'
export SENA_SERVICENOW_MAPPING_CONFIG=/etc/sena/integrations/servicenow.yaml
export SENA_SERVICENOW_WEBHOOK_SECRET='replace-with-secret'

export SENA_ENABLE_EXPERIMENTAL_ROUTES=false
```

## Forbidden weak defaults

The credible pilot profile rejects startup when any of the following are true:

- `SENA_INGESTION_QUEUE_BACKEND=memory`
- `SENA_INTEGRATION_RELIABILITY_ALLOW_INMEMORY=true`
- `SENA_BUNDLE_SIGNATURE_STRICT=false`
- missing `SENA_AUDIT_SINK_JSONL` or `SENA_AUDIT_VERIFY_ON_STARTUP_STRICT=false`
- `SENA_ENABLE_EXPERIMENTAL_ROUTES=true`
- `SENA_WEBHOOK_MAPPING_CONFIG` is set (generic webhook path)
- Slack integration variables set

## Startup invariants and validation

Run before each rollout:

```bash
python -m sena.cli.main pilot-check --format both
```

Expected pass contract:

- Exit code `0`
- `ok: true`
- no fatal check failures

## Operator assumptions (explicit)

- Operators control environment variables and secret rotation through a managed secret store.
- The deployment identity can read keyring files and write to sqlite/audit paths.
- Tenant isolation is handled outside SENA (network segmentation, auth boundary, or dedicated runtime).
- All policy changes follow a documented promotion workflow and incident rollback runbook.

## Threat model assumptions

This profile assumes:

- Shared-secret webhook signatures are not leaked.
- Host filesystem permissions prevent unauthorized writes to sqlite and audit files.
- API keys are scoped to trusted operators/services and rotated.
- No untrusted actor can modify bundle keyring material.

## What this profile still does NOT guarantee

- It does **not** provide hard multi-tenant isolation by itself.
- It does **not** protect against a fully compromised host OS/runtime user.
- It does **not** guarantee downstream Jira/ServiceNow availability or correctness.
- It does **not** replace external SIEM/SOC monitoring and response.

## Acceptance checklist

- [ ] `pilot-check` passes in CI with production-like pilot env.
- [ ] `/v1/ready` returns `status=ready` after deploy.
- [ ] one signed Jira webhook and one signed ServiceNow webhook pass end-to-end.
- [ ] audit verification passes (`/v1/audit/verify` or `sena audit verify`).
- [ ] rollback drill is run and documented for the active bundle.
