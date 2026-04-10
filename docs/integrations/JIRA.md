# Jira Integration Runbook

## What this integration is
A production-shaped, deterministic Jira approval gateway for SENA. Jira issue webhooks are normalized into `ActionProposal` objects, evaluated by policy bundles, and the resulting decision can be posted back as Jira comments and/or structured status payloads.

## What this integration is not
- Not a full Jira workflow engine replacement.
- Not a generic best-effort webhook demo.
- Not an implicit fallback path: unsupported events and malformed payloads fail deterministically.

## Supported flow
1. Jira sends webhook to `POST /v1/integrations/jira/webhook`.
2. SENA verifies authenticity with a pluggable verifier contract.
3. SENA validates and normalizes payload using a strict route mapping.
4. SENA evaluates mapped `ActionProposal` against active policy bundle.
5. SENA returns machine-readable result and optionally sends outbound Jira decision payloads.

## Configuration
Set:

```bash
export SENA_JIRA_MAPPING_CONFIG=src/sena/examples/integrations/jira_mappings.yaml
export SENA_JIRA_WEBHOOK_SECRET=local-dev-secret  # optional in local dev
```

Example mapping file: `src/sena/examples/integrations/jira_mappings.yaml`.

## Release/readiness confidence artifact
The authoritative, machine-generated confidence matrix (supported event types, signature verification modes, duplicate behavior, required metadata/field failures, and known unsupported cases) is published at `docs/artifacts/integrations/jira_servicenow_confidence_matrix.json`.

It is generated from committed mappings (`src/sena/examples/integrations/*_mappings.yaml`), committed fixtures, and test-backed assertions in `tests/fixtures/integrations/confidence_assertions.json`, and CI fails on drift via `scripts/generate_integration_confidence_matrix.py --check`.

## Local test scenario
```bash
curl -X POST http://127.0.0.1:8000/v1/integrations/jira/webhook \
  -H 'Content-Type: application/json' \
  -H 'x-atlassian-webhook-identifier: jira-dev-1' \
  -d '{
    "webhookEvent": "jira:issue_updated",
    "issue": {
      "id": "10001",
      "key": "RISK-9",
      "fields": {
        "customfield_approval_amount": 25000,
        "customfield_requester_role": "finance_analyst",
        "customfield_vendor_verified": false
      }
    },
    "user": {"accountId": "acct-99"},
    "changelog": {"items": [{"field": "status", "toString": "Pending Approval"}]}
  }'
```

## Example policy rules for Jira approvals
Use existing payment rules and map Jira fields:
- `customfield_approval_amount` -> `amount`
- `customfield_vendor_verified` -> `vendor_verified`
- `customfield_requester_role` -> `requester_role`

This lets `approve_vendor_payment` rules evaluate Jira-native approval requests deterministically.

## Deployment notes
- Configure `SENA_INTEGRATION_RELIABILITY_SQLITE_PATH` to persist Jira idempotency + outbound delivery bookkeeping.
- In production mode, Jira integration startup fails unless durable reliability storage is explicitly configured.
- In-memory connector reliability is development/demo-only (`SENA_INTEGRATION_RELIABILITY_ALLOW_INMEMORY=true`).
- Pin Jira webhook routes to explicit event types and required fields.

## Outbound reliability operator commands
- List outbound completion records:
  - API: `GET /v1/integrations/jira/admin/outbound/completions?limit=100`
  - CLI: `python -m sena.cli.main integrations-reliability --sqlite-path <reliability.db> completions`
- List outbound dead-letter records:
  - API: `GET /v1/integrations/jira/admin/outbound/dead-letter?limit=100`
  - CLI: `python -m sena.cli.main integrations-reliability --sqlite-path <reliability.db> dead-letter`
- Replay dead-letter records through configured Jira outbound client:
  - API: `POST /v1/integrations/jira/admin/outbound/dead-letter/replay` with JSON body `[<dead_letter_id>, ...]`
- Manually mark dead-letter records as redriven after external operator action:
  - API: `POST /v1/integrations/jira/admin/outbound/dead-letter/manual-redrive?note=<note>` with JSON body `[<dead_letter_id>, ...]`
  - CLI: `python -m sena.cli.main integrations-reliability --sqlite-path <reliability.db> manual-redrive --id <dead_letter_id> --note "<note>"`
- Summarize duplicate suppression counters:
  - API: `GET /v1/integrations/jira/admin/outbound/duplicates/summary`
  - CLI: `python -m sena.cli.main integrations-reliability --sqlite-path <reliability.db> duplicates-summary`
- Keep bundle naming aligned with route `policy_bundle` values.
