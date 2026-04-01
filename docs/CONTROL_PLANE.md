# Enterprise Policy Control Plane (Alpha)

This repository now includes a deterministic control-plane wedge for AI-assisted approvals:

## Implemented capabilities

1. **Policy simulation and impact analysis**
   - Compare baseline vs candidate bundles on fixed scenarios.
   - Report changed outcomes grouped by `source_system`, `workflow_stage`, and `risk_category`.
   - CLI: `--compare-policy-dir ... --simulate-scenarios src/sena/examples/scenarios/simulation_scenarios.json`
   - API: `POST /v1/simulation`

2. **Cross-system normalized approval model + portable policy packs**
   - Jira and ServiceNow connectors normalize events into the same `NormalizedApprovalEvent` contract.
   - Policy bundles target normalized attributes (not vendor-specific payload fields), enabling portability.
   - Example portable pack: `src/sena/examples/policy_packs/portable_vendor_approvals`.

3. **Policy lifecycle and promotion validation**
   - Bundle manifest supports `lifecycle` (`draft`, `candidate`, `active`, `deprecated`).
   - Bundle diff and promotion checks:
     - API: `POST /v1/bundle/diff`
     - API: `POST /v1/bundle/promotion/validate`

4. **Tamper-evident auditing**
   - Audit sink appends `previous_chain_hash` and `chain_hash`.
   - Verification:
     - API: `GET /v1/audit/verify`
     - CLI: `--verify-audit-chain path/to/audit.jsonl`

5. **Deterministic DSL hardening**
   - Additional operators: `starts_with`, `ends_with`, `matches_regex`, `exists`, `between`.
   - Operator shape validation is strict.
   - Optional bundle `context_schema` enforces deterministic fail-closed behavior.

6. **Risk/compliance explainability**
   - Decision traces include matched controls, outcome rationale, reviewer guidance, and provenance metadata.
   - Provenance includes bundle/version/schema plus decision hash and input fingerprint for replayability.

7. **API hardening and scale wedge**
   - Batch evaluation endpoint: `POST /v1/evaluate/batch` (up to 500 requests).
   - Bundle inspection endpoint: `GET /v1/bundle/inspect`.

## Alpha limitations (explicit)

- Lifecycle workflow state is file-manifest driven, not persisted in a transactional DB.
- No RBAC, OIDC, tenant partitioning, or policy authoring UI yet.
- No asynchronous long-running simulation jobs yet.
- Audit chain is local-file based (JSONL), not replicated/WORM-backed storage yet.
