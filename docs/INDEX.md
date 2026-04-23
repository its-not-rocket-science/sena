# Documentation Index (Supported Path First)

This is the default reader path.

**Product statement:** SENA is for deterministic Jira + ServiceNow approval decisioning with replayable audit evidence.

## Execution
- [Asynchronous execution model](ASYNC_EXECUTION.md)

Scope labels: `supported`, `experimental`, `labs/demo`, `legacy`.

## 1) Read this first (supported)

- `../README.md` — concise product scope, guarantees, and integration taxonomy.
- `FLAGSHIP_WORKFLOW.md` — default end-to-end workflow (run this first).
- `CONTROL_PLANE.md` — implemented runtime contract.
- `READINESS.md` — explicit maturity model (implemented, pilot-ready, not production-grade).
- `ARCHITECTURE.md` — supported boundaries and non-goals.
- `POSITIONING.md` — what SENA is and is not vs generic policy engines.
- `CANONICAL_WORKFLOW.md` — end-to-end supported workflow + evidence chain.
- `integrations/JIRA.md` and `integrations/SERVICENOW.md` — supported connector contracts.
- `integrations/SUPPORTED_PATH_READINESS_CHECKLIST.md` — Jira + ServiceNow supported-path pass/fail readiness gates.
- `OPERATIONS.md` — day-2 operator runbooks for supported surfaces.
- `SUPPORTED_VS_EXPERIMENTAL_INVENTORY.md` — crisp classification for docs/examples/scripts/API surfaces.
- Experimental API endpoints currently implemented: `/v1/integrations/webhook`, `/v1/integrations/slack/interactions` (disabled by default outside development).
- `RUNBOOKS.md` — failure-mode runbooks with copy/paste commands and pass/fail interpretation.
- `DAY2_OPERATIONS.md` — daily and incident safety checklist for on-call operators.
- `API_IDEMPOTENCY_CONTRACT.md` — payload-binding idempotency semantics and error contract.
- `PILOT_ACCEPTANCE.md` — measurable acceptance criteria.
- `INTERNAL_SOUNDNESS_GAP_ANALYSIS.md` — implementation-backed alpha→internally-sound gaps and milestones.
- `INTERNAL_SOUNDNESS_REQUIRED_NOW_TASKS.md` — issue-ready required-now execution backlog.

## 2) Supported engineering references

- `INTEGRATION_ABSTRACTION.md`
- `AUDIT_GUARANTEES.md`
- `CANONICAL_ARTIFACT_CONTRACT.md`
- `POLICY_LIFECYCLE.md`
- `POLICY_SCHEMA_EVOLUTION.md`
- `MIGRATIONS.md`
- `BUNDLE_SIGNING.md`
- `AUTH_MODEL.md`
- `STORAGE_BACKENDS.md`
- `../src/sena/MODULE_STATUS.md`

## 3) Non-default materials

These are intentionally outside the default product-reader path:

- Experimental/labs index: `EXPERIMENTAL_INDEX.md`
- Historical archive: `archive/legacy_vision.md`
