# Supported Jira + ServiceNow Test Inventory

Last updated: 2026-04-23

## Unit tests
- `tests/test_jira_integration.py`
- `tests/test_servicenow_integration.py`
- `tests/test_integration_abstraction.py`
- `tests/test_integrations_registry.py`

Focus: mapping validation, deterministic normalization, webhook verifier behavior, idempotency edge cases, outbound payload shape.

## Concurrency tests
- `tests/test_concurrency.py`
- `tests/test_concurrency_races.py`
- `tests/test_parallel_run.py`

Focus: race safety, concurrent queue/process behavior, bounded parallel execution.

## API integration tests
- `tests/test_supported_integrations_e2e.py`
- `tests/test_api.py`
- `tests/test_api_app_factory.py`
- `tests/test_api_dependencies.py`

Focus: supported endpoint behavior, policy evaluation path wiring, response contract consistency.

## Restart / recovery tests
- `tests/test_integration_reliability.py`
- `tests/test_integration_reliability_durability_evidence.py`
- `tests/test_policy_registry_disaster_recovery.py`

Focus: reliability persistence, duplicate suppression across restart, dead-letter replay/manual redrive recovery.

## Security / auth tests
- `tests/test_api_authz_security.py`
- `tests/test_api_auth_providers.py`
- `tests/test_api_middleware.py`

Focus: API key and step-up constraints, auth provider validation, request boundary controls.

## Snapshot / golden tests
- `tests/test_property_and_golden_regressions.py`
- `tests/test_replay_corpus.py`
- `tests/test_supported_integrations_confidence.py` (new)

Focus: regression lock on stable contracts and replay corpus outcomes.

---

## Highest-risk gaps identified
1. **Normalized connector contract drift detection was weak**
   - Existing tests asserted selected fields but not full canonical event contract snapshots.
2. **Replay determinism at supported endpoint layer was under-asserted**
   - Determinism checks existed in isolated paths, but endpoint-level repeated delivery equivalence coverage was limited.
3. **Webhook auth failures lacked explicit matrix coverage**
   - Missing/invalid/valid signature behavior for both supported connectors was not validated as one matrix.
4. **Restart behavior was connector-heavy, endpoint-light**
   - Durable idempotency persistence existed but not explicitly tested through supported webhook endpoints across app restarts.
5. **Malformed upstream payload negatives were partial**
   - Missing required identity-field failures were tested in connector units but not explicitly at endpoint contract level for both connectors.

## Additions in this change
- Added supported-path golden snapshot tests for canonical normalized contracts (Jira + ServiceNow).
- Added replay determinism tests across distinct deliveries for both connectors.
- Added auth failure matrix tests (missing signature, invalid signature, valid signature) for both connectors.
- Added app restart duplicate-suppression persistence tests through supported endpoints.
- Added malformed upstream payload negative tests for required identity fields at endpoint level.
- Added shared helper module for supported integration test fixtures and signature generation.

