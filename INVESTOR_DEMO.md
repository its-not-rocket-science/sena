# SENA Investor / Design-Partner Demo

## Problem

Enterprises are deploying AI assistants into workflows that can trigger high-risk actions (payments, refunds, sensitive data exports). Most controls are prompt-level guardrails or ad-hoc checks that are hard to audit.

## Why now

AI-assisted operations are moving from low-risk drafting into action-taking workflows. Compliance and risk teams need deterministic pre-execution controls before scale-out.

## Why current AI guardrails are insufficient

- Prompt-level guardrails are not deterministic policy enforcement.
- Policy intent is often buried in docs/SOPs, not executable.
- Auditors and risk teams need consistent decision records and precedence explanations.

## What SENA does today

SENA provides an alpha policy engine that:
- loads structured policy bundles
- validates rule payloads and supported operators
- evaluates actions deterministically with clear precedence
- returns audit-friendly outputs with decision IDs and bundle metadata

## 5-minute demo script

1. Start API.
   - `uvicorn sena.api.app:app --reload`
2. Show `/health` and `/bundle`.
3. Run blocked vendor payment scenario via CLI JSON output.
4. Run escalate data-export scenario.
5. Show allow scenario (no matching rules or passing conditions).
6. Highlight `decision_id`, matched rules, and precedence explanation.

## Who buys first

- Mid-market to enterprise teams with AI-enabled ops and strict internal controls:
  - finance operations
  - trust & safety / risk operations
  - data governance teams

## Future work (not yet delivered)

- Managed policy lifecycle and release workflow
- Integration connectors (ticketing, ERP, payments, CRM)
- Decision simulation and drift monitoring
- Enterprise deployment controls

## Risks / limitations

- Early alpha: no managed control plane
- No formal verification guarantees
- Local policy loading only
- Limited out-of-the-box connectors
