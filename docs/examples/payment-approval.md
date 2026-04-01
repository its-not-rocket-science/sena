# Payment Approval End-to-End Example

This example shows a realistic approval flow where:

1. An AI agent proposes a payment.
2. SENA evaluates the proposal against deterministic policy rules.
3. SENA escalates to Slack when human approval is required.

---

## 1) Example Policies

Use a policy set like the following for `approve_vendor_payment` actions.

```yaml
# bundle.yaml
bundle_name: enterprise-compliance-controls
version: 2026.04
owner: finance-risk
description: Controls for vendor payment approvals.
lifecycle: candidate
context_schema:
  amount: int?
  vendor_verified: bool?
  actor_role: str?
  currency: str?
```

```json
[
  {
    "id": "payment_block_unverified_vendor",
    "description": "Block vendor payments when vendor verification is incomplete",
    "severity": "critical",
    "inviolable": true,
    "applies_to": ["approve_vendor_payment"],
    "condition": {"field": "vendor_verified", "eq": false},
    "decision": "BLOCK",
    "reason": "Payment blocked because vendor verification is required before disbursement."
  },
  {
    "id": "payment_escalate_high_amount_non_director",
    "description": "Escalate high-value payments when actor is not finance director",
    "severity": "high",
    "inviolable": false,
    "applies_to": ["approve_vendor_payment"],
    "condition": {
      "and": [
        {"field": "amount", "gte": 10000},
        {"field": "actor_role", "neq": "finance_director"}
      ]
    },
    "decision": "ESCALATE",
    "reason": "High-value payments require finance director review."
  },
  {
    "id": "payment_allow_verified_low_risk",
    "description": "Allow lower-value verified payments from finance analysts",
    "severity": "medium",
    "inviolable": false,
    "applies_to": ["approve_vendor_payment"],
    "condition": {
      "and": [
        {"field": "vendor_verified", "eq": true},
        {"field": "amount", "lt": 10000},
        {"field": "actor_role", "in": ["finance_analyst", "finance_manager", "finance_director"]}
      ]
    },
    "decision": "ALLOW",
    "reason": "Verified low-risk payment is within delegated authority."
  }
]
```

---

## 2) Example Request Payloads

### A. AI agent proposal to `/v1/evaluate`

```http
POST /v1/evaluate
Content-Type: application/json
X-Request-Id: req_agent_20260401_001
```

```json
{
  "action_type": "approve_vendor_payment",
  "request_id": "payreq_883741",
  "actor_id": "agent-finops-17",
  "actor_role": "finance_analyst",
  "attributes": {
    "invoice_id": "INV-20491",
    "vendor_id": "vendor_548",
    "vendor_verified": true,
    "amount": 25000,
    "currency": "usd",
    "payment_method": "wire"
  },
  "facts": {
    "business_unit": "procurement",
    "quarter": "2026Q2"
  },
  "default_decision": "APPROVED",
  "strict_require_allow": true
}
```

### B. Same scenario via `/v1/integrations/webhook` (Stripe)

```http
POST /v1/integrations/webhook
Content-Type: application/json
X-Request-Id: req_webhook_20260401_009
```

```json
{
  "provider": "stripe",
  "event_type": "payment_intent.created",
  "payload": {
    "id": "evt_1Q2A3B4C",
    "data": {
      "object": {
        "amount": 25000,
        "currency": "usd",
        "metadata": {
          "vendor_verified": true,
          "requester_role": "finance_analyst",
          "requested_by": "agent-finops-17"
        }
      }
    }
  },
  "facts": {
    "source": "stripe_webhook"
  }
}
```

### C. Slack interaction callback to `/v1/integrations/slack/interactions`

Slack sends URL-encoded form data with a `payload` field:

```http
POST /v1/integrations/slack/interactions
Content-Type: application/x-www-form-urlencoded
```

```text
payload={
  "type":"block_actions",
  "user":{"id":"U074H8X1R"},
  "actions":[
    {
      "action_id":"sena_escalation_approve",
      "value":"9fb46aa6-f9c0-4473-b911-5ff3ef2d9182"
    }
  ]
}
```

---

## 3) End-to-End Walkthrough

### Step 0: Start API with Slack + webhook mapping configured

```bash
export SENA_POLICY_DIR=src/sena/examples/policies
export SENA_WEBHOOK_MAPPING_CONFIG=src/sena/examples/integrations/webhook_mappings.yaml
export SENA_SLACK_BOT_TOKEN='xoxb-***'
export SENA_SLACK_CHANNEL='#risk-reviews'
python -m uvicorn sena.api.app:app --reload
```

### Step 1: AI agent proposes payment

The agent submits a payment proposal (directly to `/v1/evaluate` or indirectly via webhook). For this example, the proposal has:

- `vendor_verified=true`
- `amount=25000`
- `actor_role=finance_analyst`

### Step 2: SENA evaluates policy rules deterministically

Rule outcomes:

- `payment_block_unverified_vendor`: **not matched** (`vendor_verified=true`)
- `payment_escalate_high_amount_non_director`: **matched** (`amount>=10000` and role is not `finance_director`)
- `payment_allow_verified_low_risk`: **not matched** (`amount` is not `<10000`)

Final decision: `ESCALATE_FOR_HUMAN_REVIEW`

Example response shape:

```json
{
  "action_type": "approve_vendor_payment",
  "outcome": "ESCALATE_FOR_HUMAN_REVIEW",
  "summary": "Escalation triggered by high-value payment rule.",
  "decision_id": "9fb46aa6-f9c0-4473-b911-5ff3ef2d9182",
  "matched_rules": [
    {
      "rule_id": "payment_escalate_high_amount_non_director",
      "matched": true,
      "decision": "ESCALATE"
    }
  ]
}
```

### Step 3: SENA sends Slack approval card

When outcome is `ESCALATE_FOR_HUMAN_REVIEW`, SENA posts a Slack message with:

- Decision metadata (decision ID, request ID, action, matched rules)
- `Approve` button (`action_id=sena_escalation_approve`)
- `Reject` button (`action_id=sena_escalation_reject`)

### Step 4: Reviewer clicks Approve (or Reject)

Slack calls `/v1/integrations/slack/interactions`. SENA parses the action and returns a deterministic callback result.

Example callback response when approved:

```json
{
  "status": "ok",
  "decision": "APPROVE",
  "decision_id": "9fb46aa6-f9c0-4473-b911-5ff3ef2d9182",
  "reviewer": "U074H8X1R"
}
```

### Step 5: Downstream execution/audit (typical integration)

A common production pattern is:

- If `APPROVE`: execute payment in ERP/payment rail.
- If `REJECT`: cancel/hold request and notify requester.
- Persist SENA decision artifacts (`decision_id`, matched rules, reasoning summary, reviewer ID) into your audit system.

This keeps policy evaluation deterministic while still allowing human control for high-risk transactions.
