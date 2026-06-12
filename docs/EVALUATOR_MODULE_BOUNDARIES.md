# Evaluator module boundaries

This note documents internal boundaries introduced to reduce maintenance risk while preserving the public API (`PolicyEvaluator.evaluate`).

## Boundary map

- `src/sena/engine/evaluator.py`
  - Orchestration entrypoint and API-preserving adapter methods.
  - Owns lifecycle sequencing (validate → evaluate rules/invariants → precedence → exception overlay → reasoning/audit assembly).

- `src/sena/engine/evaluator_components.py`
  - Pure/componentized evaluator responsibilities with explicit contracts:
    - `run_pre_evaluation_validation` (`PreEvaluationValidationResult`)
    - `evaluate_invariants`
    - `evaluate_rules`
    - `resolve_precedence` (`PrecedenceResolution`)
    - `apply_exception_overlay`
    - `assemble_reasoning_payload`
    - `build_canonical_decision_artifacts` (`CanonicalDecisionArtifacts`)
    - `assemble_audit_record` (`AuditAssemblyResult`)

## Ordering invariants (behavioral contract)

Precedence ordering remains deterministic and unchanged:

1. Invariant violations (`BLOCKED`)
2. Inviolable `BLOCK`
3. Ordinary `BLOCK`
4. `ESCALATE`
5. Configured default decision
6. Guardrails may force `BLOCKED` (`schema`, `identity`, `ai_metadata`, `strict_allow`)

Exception overlay remains post-baseline and can only move non-`APPROVED`/non-`BLOCKED` outcomes to `APPROVED`.

## Why this split

- Lowers cognitive load by isolating cohesive, testable responsibilities.
- Preserves behavior by keeping orchestration sequence centralized in `PolicyEvaluator`.
- Enables targeted unit tests for hashing/canonicalization and precedence mechanics without requiring full end-to-end evaluator setup.
