# Testing Strategy: Failure Modes, Determinism, and Migration Safety

This document defines the test posture used to prevent subtle correctness regressions in SENA's highest-risk paths: deterministic evaluator behavior, policy parsing, integrations, and audit-chain integrity.

## Objectives

- Preserve decision determinism for equivalent inputs across runs and deployments.
- Fail closed for malformed policy and integration payloads.
- Preserve audit-chain tamper evidence under record edits, reordering, truncation, and replay.
- Keep integration entrypoints idempotent so retries do not create duplicate side effects.

## Test strategy by layer

### 1) Unit tests

Use unit tests for narrow, deterministic contracts and precedence behavior.

Coverage focus:
- **Evaluator precedence and reasoning**: BLOCK vs ESCALATE vs ALLOW ordering, strict allow mode, schema validation short-circuiting.
- **Policy parsing and validation**: malformed bundle manifest, bad condition shapes, unsupported schema evolution fields, duplicate rule IDs.
- **Integration normalization**: route resolution, required-field extraction, delivery-id computation, unsupported event handling.
- **Audit chain primitives**: chain hash computation, append semantics, sequence monotonicity, duplicate decision ID detection.

Design constraints:
- Prefer fixed fixtures over randomized values for readability.
- Assert canonical decision artifacts (`canonical_replay_payload`, `decision_hash`, `input_fingerprint`, matched controls) rather than volatile metadata (`decision_id`, timestamps).

### 2) Property-based tests

Use Hypothesis where a small invariant can be violated by many structurally different inputs.

Coverage focus:
- **Determinism invariants**: same semantic input => same outcome + same `decision_hash`.
- **Parser robustness**: malformed text and near-valid structures never crash unpredictably.
- **Lifecycle algebra**: `diff(x, x)` has no changes; set operations are stable for reordered rules.
- **Audit hash stability**: canonical hash function is stable for equal payloads.

Runtime controls:
- Keep example counts bounded for local feedback.
- Prefer strategies that generate JSON-like structures without NaN/Infinity drift.

### 3) Integration tests

Use API/service-level tests to verify cross-component behavior with realistic envelopes.

Coverage focus:
- **End-to-end evaluate/webhook paths** with app factory + test client.
- **Idempotency behavior** for API keys and connector delivery IDs.
- **Error envelope stability** and DLQ routing for malformed external payloads.
- **Bundle/version checks** to prevent wrong-policy execution at integration boundaries.

Regression pattern:
- Assert both response shape and persistent state implications (idempotency store rows, DLQ entries, audit append behavior).

### 4) Replay determinism tests

Replay tests are the highest-signal guard against silent policy drift.

Coverage focus:
- Re-evaluate previously captured proposals/traces and compare against baseline outcome/materialized controls.
- Verify drift reports detect mapping/config changes that alter action type or control matches.
- Include replay fixtures from real integration payloads to protect envelope contracts.

Key assertion fields:
- `outcome`
- `decision_hash`
- `matched_rule_ids`
- `missing_evidence`
- escalation rates and changed-control counters

## Current gaps and risk-ranked improvements

1. **Idempotency-key payload binding (High)**  
   Current API idempotency tests assert cache reuse for same key, but do not assert behavior when the same key is reused with a different payload. Add conflict tests to prevent accidental cross-request replay.

2. **Replay corpus breadth (High)**  
   Replay tests cover representative cases but not enough historical/production-shaped envelopes. Add a curated replay corpus (approved baseline snapshots) for each integration provider.

3. **Audit-chain adversarial rewrites (Medium)**  
   Existing tests cover tampering and duplicates; extend with recomputed-hash attacks, segment-manifest divergence, and sequence-gap manipulations across rotated segments.

4. **Parser compatibility matrix (Medium)**  
   Add matrix tests for policy schema evolution (`schema_version`, optional fields, deprecated aliases) so parser changes cannot silently alter rule semantics.

5. **Concurrency/idempotency race windows (Medium)**  
   Add targeted multithreaded tests for concurrent duplicate deliveries and concurrent idempotency-key writes at API layer.

## New example regression tests

The suite now includes focused examples for subtle correctness failures:

- Determinism for semantically equivalent inputs with different key ordering.
- Audit verification that still fails after a tampered record has its chain hash recomputed.
- Integration duplicate-delivery rejection to enforce idempotent normalization.
