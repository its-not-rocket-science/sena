# SENA

SENA is an **alpha deterministic policy-enforcement engine for AI-assisted enterprise approval workflows**.

It evaluates high-risk workflow actions against structured policy bundles and returns an auditable decision (`APPROVED`, `BLOCKED`, `ESCALATE_FOR_HUMAN_REVIEW`) with decision reasoning and machine-readable trace data.

## Who this is for

- **Primary buyer/user:** Compliance, risk, and operations leaders introducing AI assistants into approval workflows.
- **Primary user in product flow:** Operations analysts, support leads, and workflow owners who need deterministic pre-execution policy checks.

## Core use cases (current alpha)

1. **Vendor payments:** block unverified vendors, escalate high-value disbursements.
2. **Refunds / chargebacks:** block invalid refund attempts, escalate exceptions.
3. **Customer data export:** block high-risk data exports and route sensitive exports to human review.

## Supported architecture (current)

```text
Action Proposal + Context Facts
              |
              v
Policy Bundle Loader (YAML/JSON-compatible)
              |
              v
Policy Validation + Safe Condition Interpreter
              |
              v
Deterministic Evaluator (precedence model)
              |
              v
Decision + Audit Record + Reasoning
```

### Policy DSL

Rules are structured objects with:
- `id`, `description`, `severity`, `inviolable`
- `applies_to` action types
- `condition` as structured expressions
- `decision` (`ALLOW`, `BLOCK`, `ESCALATE`)
- `reason`

Supported operators:
- Comparison: `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `contains`
- Logical: `and`, `or`, `not`

## Quickstart

### Install

```bash
pip install -e .
```

### CLI example

```bash
python -m sena.cli.main \
  src/sena/examples/scenarios/demo_vendor_payment_block_unverified.json \
  --policy-dir src/sena/examples/policies \
  --policy-bundle-name enterprise-demo \
  --bundle-version 2026.03 \
  --json
```

### API example

```bash
uvicorn sena.api.app:app --reload
```

```bash
curl -X POST http://127.0.0.1:8000/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "action_type": "approve_vendor_payment",
    "attributes": {
      "amount": 15000,
      "vendor_verified": false,
      "requester_role": "finance_analyst"
    },
    "facts": {}
  }'
```

## Example output (abridged)

```json
{
  "decision_id": "dec_a1b2c3d4e5f6",
  "outcome": "BLOCKED",
  "summary": "Decision dec_a1b2c3d4e5f6: BLOCKED due to inviolable policy constraints (...)",
  "policy_bundle": {
    "bundle_name": "enterprise-demo",
    "version": "2026.03",
    "loaded_from": "/.../src/sena/examples/policies"
  },
  "reasoning": {
    "precedence_explanation": "One or more inviolable BLOCK rules matched..."
  },
  "audit_record": {
    "matched_rule_ids": ["payment_block_unverified_vendor"]
  }
}
```

## Limitations (alpha honesty)

- In-process engine only (no distributed control plane).
- Local-file policy loading only.
- No policy authoring UI.
- No connectors to ticketing/ERP/payment providers yet.
- No formal verification claims.

## Roadmap (near-term)

- Policy bundle lifecycle: versioning, promotion, and change controls.
- Workflow adapters (payment ops, CRM/support, data-access operations).
- Simulation mode for policy change impact analysis.
- Enhanced audit export formats for compliance workflows.

## Legacy context

Historical research-prototype modules are retained under `src/sena/legacy` and are **not** the supported product path.
See `docs/ARCHITECTURE.md`, `docs/MIGRATION.md`, and `docs/archive/legacy_vision.md`.
