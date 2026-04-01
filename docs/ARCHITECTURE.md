# SENA Architecture (Supported vs Legacy)

## Supported architecture (current product path)

SENA's supported path is a deterministic compliance engine:

1. **Policy bundle loading** (`sena.policy.parser`)
2. **Policy validation** (`sena.policy.validation`)
3. **Safe condition interpretation** (`sena.policy.interpreter`)
4. **Deterministic evaluation + precedence** (`sena.engine.evaluator`)
5. **Operational interfaces** (`sena.cli.main`, `sena.api.app`)

## Runtime surfaces

### CLI
- Single-shot scenario evaluation
- Coverage validation toggles

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

Bundle metadata now includes:
- `schema_version`
- deterministic `integrity_sha256` over policy files
- `policy_file_count`

## Deterministic decision flow

1. Build context from action attributes + facts.
2. Evaluate applicable rules via allowed operators only.
3. Apply precedence:
   - inviolable `BLOCK`
   - ordinary `BLOCK`
   - `ESCALATE`
   - configured default decision (`APPROVED` by default)
4. Emit `EvaluationTrace` + `AuditRecord` with input fingerprint and decision hash.

## Observability seam

- JSON structured logs from API runtime.
- Request correlation via `x-request-id`.
- Optional JSONL audit sink file append (`SENA_AUDIT_SINK_JSONL`) for integration with external pipelines.

## Deprecated / legacy architecture

Historical modules under `src/sena/legacy/*` are retained for reference only. They are not part of the supported enterprise policy engine path.
