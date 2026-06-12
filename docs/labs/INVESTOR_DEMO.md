# SENA Investor / Design-Partner Demo

## One-line positioning

SENA is an **alpha deterministic policy control plane for AI-assisted enterprise approval workflows**, with Jira + ServiceNow as the supported integration wedge.

## What SENA does today (implemented)

- Evaluates actions deterministically from versioned policy bundles.
- Returns explicit outcomes (`APPROVED`, `BLOCKED`, `ESCALATE_FOR_HUMAN_REVIEW`) with rationale.
- Provides promotion/simulation evidence primitives for controlled policy release.
- Supports normalized integration depth for Jira + ServiceNow.
- Provides hash-linked audit verification.

## What SENA does not claim today

- Not a generalized AI safety platform.
- Not formal verification.
- Not enterprise-complete control plane UX/IAM.
- Generic webhook + Slack routes are experimental, not productized depth.

## 5-minute demo script (v1 API)

1. Start API: `uvicorn sena.api.app:app --reload`
2. Show health/readiness: `GET /v1/health`, `GET /v1/ready`
3. Run blocked scenario (`demo_vendor_payment_block_unverified.json`) via CLI.
4. Run escalation scenario (`demo_customer_export_escalate_dpo_review.json`) via CLI.
5. Run allow scenario (`demo_refund_allow_standard.json`) via CLI.
6. Show decision evidence fields (`decision_id`, matched rules, bundle metadata, trace).

## Who buys first

Teams operating AI-assisted workflows with real compliance pressure:
- finance/risk operations,
- change management and IT governance,
- data governance programs.

## Near-term roadmap focus

1. Harden Jira + ServiceNow design-partner workflows.
2. Enforce simulation-backed promotion gates.
3. Raise operational maturity for pilot readiness.
