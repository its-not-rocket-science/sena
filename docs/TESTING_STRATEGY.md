# Testing Strategy: Failure Modes, Determinism, and Migration Safety

This document explains the test posture used to make SENA safe to ship under real-world failures, not only happy paths.

## Why this strategy

The control plane and evaluator sit on high-consequence paths. A confidence-oriented test suite must prove:

- malformed or adversarial inputs fail clearly,
- evaluator behavior remains deterministic,
- lifecycle/promotion guardrails cannot be bypassed,
- migrations preserve operability for older persisted states,
- API and integration envelopes remain stable for downstream consumers.

## Coverage areas

### 1) Failure modes (unit + integration)

The suite intentionally stresses:

- malformed policy bundles and parser failures,
- duplicate rule IDs in promotion targets,
- invalid lifecycle transitions,
- missing identity/context in strict allow mode,
- conflicting rules and precedence behavior,
- invalid integration payloads and missing required fields,
- invalid content-length headers,
- payload size enforcement,
- timeout behavior and unauthorized access handling,
- audit chain verification failures.

### 2) Property-based invariants

Hypothesis-based tests focus on high-value invariants:

- evaluator determinism for same input material,
- lifecycle diff idempotence (`diff(x, x)` has no changes),
- audit hash stability for same inputs,
- parser resilience against malformed payloads.

These tests are bounded to keep local runtime practical.

### 3) Golden-file regression tests

Golden fixtures enforce stability for externally visible and operator-facing structures:

- API error envelopes,
- bundle diff output,
- promotion validation output,
- normalized integration payload shape.

Golden tests normalize volatile fields (timestamps/request IDs generated at runtime) before assertion.

### 4) Migration regression fixtures

Fixtures under `tests/fixtures/migrations/` model historical states:

- `legacy_bundle_v1/` captures an older bundle format and content,
- `storage_states/legacy_registry_v1.sql` captures a pre-enhancement SQLite registry.

Tests then migrate forward and verify schema/application compatibility invariants.

## Fast feedback principles

To keep the suite useful for local development:

- tests are behavior-dense rather than volume-heavy,
- property-based tests cap examples,
- migration tests reuse lightweight fixture states,
- golden tests assert entire envelopes to maximize signal per test.
