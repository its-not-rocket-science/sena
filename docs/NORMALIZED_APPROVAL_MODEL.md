# Normalized Approval Event Model

## Why this exists

SENA's differentiation is not merely that it evaluates policy rules; it is that it provides a **portable, auditable, deterministic control plane** for approvals across heterogeneous systems.

External workflow tools (Jira, ServiceNow, ERP approvals, refund tooling, data export requests) all emit different payload shapes. If policy logic consumes those raw payloads directly, then policy semantics become coupled to each vendor's schema drift.

The normalized event model introduces a strict intermediate contract:

1. **Source-system normalization layer** converts external payloads into one deterministic schema.
2. **Policy evaluation layer** consumes ActionProposal objects derived from that schema.

This separation enables portability, stronger governance, and reusable policy bundles.

## Canonical normalized event

`NormalizedApprovalEvent` fields:

- `source_system`
- `source_event_type`
- `source_object_type`
- `source_object_id`
- `workflow_stage`
- `requested_action`
- `actor` (`actor_id`, `actor_role`)
- `risk_attributes`
- `evidence_references`
- `correlation_key`
- `idempotency_key`
- `request_id`
- `attributes`
- `source_metadata`

Required normalized keys are validated before policy evaluation.

## Deterministic architecture pattern

```text
External payload -> Integration route mapping -> NormalizedApprovalEvent -> ActionProposal -> PolicyEvaluator
```

Normalization is responsible for:

- payload path resolution and required field checks,
- idempotency and correlation assignment,
- risk/evidence extraction,
- explicit source metadata tagging.

Evaluation is responsible for:

- rule matching,
- precedence and deterministic outcomes,
- decision trace + audit output.

## Examples across workflow types

### 1) Jira vendor payment approval

- `source_system`: `jira`
- `source_object_type`: `jira_issue`
- `workflow_stage`: `pending_approval`
- `requested_action`: `approve_vendor_payment`
- `risk_attributes`: approval amount, vendor verification flag

### 2) ServiceNow change approval

- `source_system`: `servicenow`
- `source_object_type`: `change_request`
- `workflow_stage`: `requested`
- `requested_action`: `approve_vendor_payment`
- `risk_attributes`: risk level + emergency/privileged/out-of-hours flags
- `evidence_references`: CAB evidence identifiers

### 3) Generic webhook (Stripe payment intent)

- `source_system`: `stripe`
- `source_object_type`: `payment_intent`
- `workflow_stage`: `created`
- `requested_action`: `approve_vendor_payment`
- `risk_attributes`: amount + vendor verification

## Why this creates differentiation

This model shifts the product narrative from "we have rules" to:

- **Portable**: one approval control model across multiple systems.
- **Auditable**: consistent event lineage (`source_*`, `correlation_key`, `idempotency_key`).
- **Deterministic**: explicit normalization failures and replay safety.
- **Extensible**: new integrations add route mappings without rewriting evaluator semantics.

In practice, SENA becomes the approval control plane that organizations can standardize on while keeping their existing workflow tools.
