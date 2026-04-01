# SENA Architecture (Supported vs Legacy)

## Product architecture intent

SENA is architected as a deterministic policy-enforcement and governance engine for AI-assisted enterprise workflows.

The architecture emphasizes:
- deterministic evaluation behavior,
- normalized cross-system inputs,
- auditable decision traces,
- lifecycle-controlled policy bundles,
- replay/simulation support,
- explicit human escalation outcomes.

## Supported architecture (current product path)

SENA's supported path is implemented in `src/sena/*`:

1. **Policy bundle loading** (`sena.policy.parser`)
2. **Policy validation** (`sena.policy.validation`)
3. **Safe condition interpretation** (`sena.policy.interpreter`)
4. **Deterministic evaluation + precedence** (`sena.engine.evaluator`)
5. **Operational interfaces** (`sena.cli.main`, `sena.api.app`)

This path is the source of truth for current capability claims.

## Runtime surfaces

### CLI
- Single-shot scenario evaluation
- Coverage validation toggles
- Deterministic simulation and compare flows

### API
- Versioned endpoints under `/v1`
- Unversioned aliases are deprecated stubs returning `410 Gone`
- Request ID propagation (`x-request-id`) and structured error envelope
- Optional API key middleware for self-hosted baseline controls
- Supported integration depth: Jira + ServiceNow normalized approval endpoints
- Experimental integration endpoints: generic webhook + Slack interactions

## Policy bundle model

Policy bundles are local directories containing:
- Rule files (`*.yaml`, `*.yml`, `*.json`) with list-of-rule payloads
- Optional manifest (`bundle.yaml|yml|json`) validated against schema

Bundle metadata includes:
- `schema_version`
- deterministic `integrity_sha256` over policy files
- `policy_file_count`
- lifecycle state (`draft`, `candidate`, `active`, `deprecated`)

## Deterministic decision flow

1. Build context from action attributes + facts.
2. Evaluate applicable rules via allowed operators only.
3. Apply precedence:
   - inviolable `BLOCK`
   - ordinary `BLOCK`
   - `ESCALATE`
   - configured default decision (`APPROVED` by default)
4. Emit `EvaluationTrace` + `AuditRecord` with input fingerprint and decision hash.

## Governance evidence flow

SENA exposes release-evidence primitives rather than full governance automation:

- Bundle diff + promotion validation for controlled policy rollout.
- Simulation outputs for baseline-vs-candidate comparisons.
- Trace/provenance/audit hashing for post-decision review.
- Human escalation outcomes for review queue handoff.

## Observability seam

- JSON structured logs from API runtime.
- Request correlation via `x-request-id`.
- Optional JSONL audit sink file append (`SENA_AUDIT_SINK_JSONL`) for integration with external pipelines.

## Maturity boundary

SENA is currently alpha and should be positioned as deterministic governance infrastructure for pilots and controlled deployments.

Not yet implemented as production-complete architecture:
- HA multi-region control plane,
- first-class tenant isolation,
- fully integrated OIDC/RBAC admin plane,
- replicated/WORM-native audit persistence,
- asynchronous job orchestration for large simulation workloads.

## Deprecated / legacy architecture

Historical modules under `src/sena/legacy/*` are retained for reference only. They are not part of the supported SENA product path.
