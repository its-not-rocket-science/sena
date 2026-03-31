# SENA

**Syncretic Evolutionary Neuro-symbolic Architecture (SENA)** now focuses on a narrow, demonstrable wedge:

> A deterministic policy-enforcement engine for AI-assisted enterprise compliance workflows.

This repository contains an alpha MVP that can evaluate high-risk workflow actions (payments, refunds, customer-data exports), apply executable policy constraints, and return auditable decisions.

## What SENA does today

SENA accepts:
1. a structured action proposal,
2. structured context facts,
3. human-reviewable YAML policy files,

and deterministically returns one decision:
- `APPROVED`
- `BLOCKED`
- `ESCALATE_FOR_HUMAN_REVIEW`

Each decision includes a machine-readable audit trace and a human-readable explanation.

## Why this wedge

Many enterprises already use AI assistants in support workflows, but approval and compliance controls are often ad-hoc. SENA’s MVP addresses that specific problem by turning policy into executable constraints and enforcing them before action execution.

## Current architecture

```text
Action Proposal + Facts
        |
        v
YAML Policy Parser/Validator (safe DSL, no eval)
        |
        v
Deterministic Evaluator
        |
        v
Decision + Audit Trace
```

## Policy DSL (safe, structured)

Rules are YAML objects with explicit fields:
- `id`
- `description`
- `severity`
- `inviolable`
- `applies_to`
- `condition` (structured expression)
- `decision` (`ALLOW`, `BLOCK`, `ESCALATE`)
- `reason`

Supported condition operators:
- `eq`, `neq`, `gt`, `gte`, `lt`, `lte`
- `in`, `not_in`, `contains`
- `and`, `or`, `not`

No dynamic code execution is used.

## Quickstart

### Install

```bash
pip install -e .
```

### Run CLI demo

```bash
python -m sena.cli.main src/sena/examples/scenarios/blocked_payment.json
python -m sena.cli.main src/sena/examples/scenarios/allowed_refund.json
python -m sena.cli.main src/sena/examples/scenarios/needs_review_export.json --json
```

### Run API

```bash
uvicorn sena.api.app:app --reload
```

Then evaluate a proposal:

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

## Project layout

```text
src/sena/
  core/
  policy/
  engine/
  api/
  cli/
  examples/
    policies/
    scenarios/
tests/
```

## Current limitations

- This is an in-process engine; no persistence layer or distributed execution yet.
- Policies are loaded from local files only.
- No UI policy editor yet.
- No integration adapters for enterprise systems yet.

## Roadmap (near-term)

- Versioned policy bundles and signed policy releases.
- Workflow connectors (ticketing, payment ops, data access tooling).
- Decision simulation mode for policy change impact analysis.
- Richer observability and trace export formats.
