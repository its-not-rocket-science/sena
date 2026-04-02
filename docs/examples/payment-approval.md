# Payment Approval Example (Experimental Integration Path)

> This example uses **experimental** integration surfaces (`/v1/integrations/webhook` and `/v1/integrations/slack/interactions`).
> For supported production-depth integrations, use the Jira + ServiceNow flagship example.

This walkthrough shows an AI-assisted vendor payment proposal that is escalated for human review.

## Goal

Demonstrate deterministic policy behavior for a payment request:

1. Proposal is evaluated by SENA policy.
2. High-risk condition triggers `ESCALATE_FOR_HUMAN_REVIEW`.
3. Human action can be returned through Slack interaction callback.

## Experimental endpoints used

- `POST /v1/integrations/webhook`
- `POST /v1/integrations/slack/interactions`

## Supported alternative for production-depth pilots

Use these supported routes instead:
- `POST /v1/integrations/jira/webhook`
- `POST /v1/integrations/servicenow/webhook`

## Example payload shape (webhook)

```json
{
  "provider": "stripe",
  "event_type": "payment_intent.created",
  "payload": {
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
  }
}
```

## Expected deterministic result

For a policy where high amount + non-director requires escalation:
- outcome is `ESCALATE_FOR_HUMAN_REVIEW`,
- decision includes matched rule IDs and deterministic decision metadata.
