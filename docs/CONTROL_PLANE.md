# Enterprise Policy Control Plane (Alpha)

This repository now includes a deterministic control-plane wedge for AI-assisted approvals:

## Implemented capabilities

1. **Policy simulation and impact analysis**
   - Compare baseline vs candidate bundles on fixed scenarios.
   - CLI: `--compare-policy-dir ... --simulate-scenarios examples/simulation_scenarios.json`
   - API: `POST /v1/simulation`

2. **Policy lifecycle and promotion validation**
   - Bundle manifest supports `lifecycle` (`draft`, `candidate`, `active`, `deprecated`).
   - Bundle diff and promotion checks:
     - API: `POST /v1/bundle/diff`
     - API: `POST /v1/bundle/promotion/validate`

3. **Tamper-evident auditing**
   - Audit sink appends `previous_chain_hash` and `chain_hash`.
   - Verification:
     - API: `GET /v1/audit/verify`
     - CLI: `--verify-audit-chain path/to/audit.jsonl`

4. **Deterministic DSL hardening**
   - Additional operators: `starts_with`, `ends_with`, `matches_regex`, `exists`, `between`.
   - Operator shape validation is strict.
   - Optional bundle `context_schema` enforces deterministic fail-closed behavior.

5. **API hardening and scale wedge**
   - Batch evaluation endpoint: `POST /v1/evaluate/batch` (up to 500 requests).
   - Bundle inspection endpoint: `GET /v1/bundle/inspect`.

## Alpha limitations (explicit)

- Lifecycle workflow state is file-manifest driven, not persisted in a transactional DB.
- No RBAC, OIDC, tenant partitioning, or policy authoring UI yet.
- No asynchronous long-running simulation jobs yet.
- Audit chain is local-file based (JSONL), not replicated/WORM-backed storage yet.
