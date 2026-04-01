# SENA Control Plane (Alpha)

SENA's control-plane surface is an **alpha governance layer** for AI-assisted enterprise workflows.

Its purpose is to make policy decisions deterministic, traceable, and release-controlled across heterogeneous workflow systems.

## Positioning summary

SENA is not a generalized AI safety platform or a formal verification framework. It is a deterministic policy-enforcement engine with operational controls for evidence-backed policy releases.

## Implemented capabilities

1. **Deterministic policy simulation and impact analysis**
   - Compare baseline vs candidate bundles on fixed scenarios.
   - Report changed outcomes grouped by `source_system`, `workflow_stage`, and `risk_category`.
   - CLI: `--compare-policy-dir ... --simulate-scenarios src/sena/examples/scenarios/simulation_scenarios.json`
   - API: `POST /v1/simulation`

2. **Cross-system normalized approval model + portable policy packs (supported depth)**
   - Jira and ServiceNow connectors normalize events into the same `NormalizedApprovalEvent` contract.
   - Policy bundles target normalized attributes (not vendor-specific payload fields), improving portability.
   - Example portable pack: `src/sena/examples/policy_packs/portable_vendor_approvals`.

3. **Policy lifecycle and promotion validation**
   - Bundle manifest supports `lifecycle` (`draft`, `candidate`, `active`, `deprecated`).
   - Bundle diff and promotion checks:
     - API: `POST /v1/bundle/diff`
     - API: `POST /v1/bundle/promotion/validate`

4. **Auditable decision traces and tamper-evident audit chain**
   - Decision output includes rationale, reviewer guidance, and provenance metadata.
   - Audit sink appends `previous_chain_hash` and `chain_hash`.
   - Verification:
     - API: `GET /v1/audit/verify`
     - CLI: `--verify-audit-chain path/to/audit.jsonl`

5. **Deterministic DSL hardening**
   - Additional operators: `starts_with`, `ends_with`, `matches_regex`, `exists`, `between`.
   - Operator shape validation is strict.
   - Optional bundle `context_schema` enforces deterministic fail-closed behavior.

6. **Release evidence workflow primitives**
   - Bundle metadata and provenance support release records.
   - Diff/simulation outputs provide before/after evidence for policy promotions.
   - Decision hashes + input fingerprints support replay-oriented investigation.

7. **API hardening and scale wedge**
   - Batch evaluation endpoint: `POST /v1/evaluate/batch` (up to 500 requests).
   - Bundle inspection endpoint: `GET /v1/bundle/inspect`.

## Surface boundaries (hardening pass)

Supported integration depth:
- `POST /v1/integrations/jira/webhook`
- `POST /v1/integrations/servicenow/webhook`

Experimental integration endpoints (evaluation-only):
- `POST /v1/integrations/webhook`
- `POST /v1/integrations/slack/interactions`

## Current maturity and explicit limitations

SENA remains alpha. The current implementation supports deterministic governance pilots, not full enterprise platform maturity.

Current limitations:

- Lifecycle workflow state is file-manifest driven unless explicitly using the optional SQLite registry path.
- No built-in RBAC, OIDC, tenant partitioning, or policy authoring UI yet.
- No asynchronous long-running simulation jobs yet.
- Audit chain is local-file based (JSONL), not replicated/WORM-backed storage yet.
- Integration depth is strongest for Jira + ServiceNow; generic webhook and Slack paths are explicitly experimental.
