# SENA Investor Demo (Wedge MVP)

## 1) Wedge

SENA is focused on one narrow product wedge:

**Deterministic policy enforcement for AI-assisted enterprise approval workflows.**

This is intentionally narrower than general AI safety. The current MVP covers policy checks for:
- vendor payments,
- refunds,
- customer-data exports.

## 2) Problem

AI copilots can draft or recommend operational actions quickly, but regulated and high-risk actions still require reliable controls. Teams need:
- consistent enforcement of compliance policy,
- deterministic outcomes for auditability,
- transparent decision traces for internal and external review.

Rule logic hidden inside prompts or ad-hoc code is hard to audit and easy to drift.

## 3) Workflow (5-minute live demo)

1. Load policies from YAML.
2. Send a structured action proposal with supporting facts.
3. SENA evaluates rules deterministically.
4. SENA returns one outcome:
   - `APPROVED`
   - `BLOCKED`
   - `ESCALATE_FOR_HUMAN_REVIEW`
5. SENA returns an audit trace listing matched rules and reasons.

## 4) Why deterministic enforcement matters

For high-risk workflows, “usually correct” is not enough.

Deterministic policy enforcement provides:
- repeatable outcomes for identical inputs,
- explicit and reviewable control logic,
- clear separation between AI recommendation generation and policy gating,
- auditable evidence for governance/compliance functions.

## 5) What is implemented now

- Safe policy DSL using structured YAML conditions (no Python `eval`).
- Policy parser + validation.
- Condition interpreter with a constrained set of operators.
- Evaluation engine with outcome prioritization (`BLOCK` > `ESCALATE` > `ALLOW`).
- Machine-readable evaluation trace.
- Human-readable explanation output.
- CLI demo for local scenario playback.
- FastAPI endpoint for programmatic evaluation.
- Example policies and scenarios for payments/refunds/data exports.
- Basic pytest coverage.

## 6) Future work (not yet implemented)

- Policy versioning and approval lifecycle.
- Identity/role integrations with enterprise systems.
- Persistent audit log storage and signed trace artifacts.
- Multi-tenant policy management.
- Connectors to workflow engines and case-management tools.
- Benchmarks on real production workload characteristics.

## 7) Demo commands

```bash
# CLI examples
python -m sena.cli.main src/sena/examples/scenarios/blocked_payment.json
python -m sena.cli.main src/sena/examples/scenarios/allowed_refund.json
python -m sena.cli.main src/sena/examples/scenarios/needs_review_export.json --json

# API
uvicorn sena.api.app:app --reload
```
