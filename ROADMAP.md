# SENA Roadmap (Compliance Engine Focus)

## Positioning

SENA is focused on a single wedge: **deterministic policy enforcement for AI-assisted enterprise approval workflows**.

This roadmap reflects the current alpha scope. It does not assume formal verification, robotics safety scope, or broad AGI-safety claims.

---

## Current phase (March 2026)

**Phase: Alpha Product Validation**

Delivered:
- Structured policy models and validation
- Safe interpreted policy DSL (no dynamic code execution in supported path)
- Deterministic precedence-based evaluator
- CLI and FastAPI endpoints
- Auditable decision traces and bundle metadata

---

## Phase 1 — Design Partner Readiness (next)

- Harden policy bundle management conventions
- Add integration adapters for one approval system and one ticketing system
- Extend audit record export (JSONL/webhook)
- Add policy simulation tooling for rule-change testing

Success criteria:
- 2–3 design-partner workflows runnable end-to-end
- Repeatable policy pack setup for payments/refunds/data export

---

## Phase 2 — Operational Controls

- Role-based policy administration model
- Policy release workflow (draft/stage/prod)
- Tamper-evident decision log options
- Deployment hardening guidance (container + observability baseline)

Success criteria:
- Compliance team can manage policy lifecycle with engineering support
- Ops team can monitor decision quality and escalation volume

---

## Phase 3 — Broader Workflow Coverage

- Additional workflow packs (account reinstatement, vendor onboarding)
- More robust schema support and payload contracts
- Connector ecosystem expansion

Success criteria:
- Multiple high-risk workflows covered by deterministic policy checks

---

## Out of scope (for now)

- Robotics safety platform
- General-purpose AI orchestration framework
- Formal verification guarantees
- Benchmark claims not backed by repeatable artifacts
