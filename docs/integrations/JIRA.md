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

## Failure behavior matrix
- Unsupported event type → `jira_unsupported_event_type`
- Missing required fields / actor identity → `jira_missing_required_fields`
- Invalid mapping config → `jira_invalid_mapping`
- Duplicate deliveries → stable `duplicate_ignored` response (`jira_duplicate_delivery`)
- Policy bundle mismatch/not found → `jira_policy_bundle_not_found`
- Timeout/partial failures → deterministic response object with status + errors

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
- Use a durable external idempotency store for multi-instance deployments (the included in-memory store is process-local).
- Pin Jira webhook routes to explicit event types and required fields.
- Keep bundle naming aligned with route `policy_bundle` values.
