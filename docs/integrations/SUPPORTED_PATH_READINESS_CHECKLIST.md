# Supported-Path Readiness Checklist (Jira + ServiceNow)

## Scope
This checklist applies only to the **supported** Jira + ServiceNow inbound-to-decision path:
- inbound webhook verification
- normalization
- evaluation
- escalation / decision payload generation
- outbound delivery / retry / dead-letter
- replayability
- bundle/version visibility

It explicitly excludes experimental connectors.

Experimental HTTP connectors currently implemented but non-default:
- `POST /v1/integrations/webhook`
- `POST /v1/integrations/slack/interactions`

## Readiness gates (pass/fail)

### 1) Inbound verification
- [ ] **PASS**: Connector rejects invalid signatures with `401` and stable code.
- [ ] **PASS**: Connector rejects missing signature when webhook secret is configured.
- [ ] **PASS**: Current + previous rotating secrets are both accepted.
- [ ] **PASS**: `pilot` and `production` startup fail closed when Jira/ServiceNow is enabled without webhook secrets (allow-all verifier disabled outside development).
- [ ] **PASS**: Duplicate deliveries return stable `status=duplicate_ignored` response.

### 1b) Route surface gating by runtime mode
- [ ] **PASS**: In `pilot` and `production`, experimental HTTP routes are absent by default (`404`).
- [ ] **PASS**: In `development`, experimental HTTP routes remain available and emit `x-sena-surface-stage: experimental`.
- [ ] **PASS**: Explicit opt-in (`SENA_ENABLE_EXPERIMENTAL_ROUTES=true`) can re-enable experimental routes for controlled pilot/prod testing.

Evidence:
- `tests/test_api.py::test_jira_webhook_signature_verification_*`
- `tests/test_api.py::test_servicenow_webhook_signature_verification_*`
- `tests/test_api.py::test_startup_fails_in_pilot_without_jira_secret`
- `tests/test_api.py::test_startup_fails_in_pilot_without_servicenow_secret`
- `tests/test_api.py::test_development_mode_allows_missing_supported_connector_secrets_with_warning`
- `tests/test_api.py::test_jira_webhook_duplicate_delivery_returns_stable_duplicate_response`
- `tests/test_api.py::test_servicenow_webhook_duplicate_delivery_returns_stable_duplicate_response`
- `tests/test_api.py::test_pilot_mode_disables_experimental_integration_routes_by_default`
- `tests/test_api.py::test_production_mode_disables_experimental_integration_routes_by_default`
- `tests/test_api.py::test_development_mode_keeps_experimental_routes_enabled_by_default`
- `tests/test_api.py::test_pilot_mode_can_explicitly_enable_experimental_routes`

### 2) Normalization + stable contracts
- [ ] **PASS**: Canonical normalization replay payload excludes volatile timestamp fields.
- [ ] **PASS**: Canonical replay payload hash is emitted in `determinism_contract`.
- [ ] **PASS**: Unsupported or malformed payloads fail closed with stable error codes.
- [ ] **PASS**: Error details include connector + stage for deterministic triage.

Evidence:
- `tests/test_api.py::test_jira_webhook_happy_path_returns_machine_readable_payload`
- `tests/test_api.py::test_servicenow_webhook_happy_path_returns_machine_readable_payload`
- `tests/test_supported_integrations_e2e.py`

### 3) Evaluation + decision artifact
- [ ] **PASS**: Policy evaluation returns deterministic decision artifact (`decision_hash`, canonical replay payload hash).
- [ ] **PASS**: Mapped action proposal and normalized event are both visible for audit traceability.
- [ ] **PASS**: Route-mapped policy bundle mismatch fails with explicit bundle-not-found error.

Evidence:
- `tests/test_supported_integrations_e2e.py`
- `tests/test_api.py::test_jira_webhook_*`
- `tests/test_api.py::test_servicenow_webhook_*`

### 4) Outbound delivery + retry/dead-letter
- [ ] **PASS**: Outbound duplicate suppression is idempotent by operation key.
- [ ] **PASS**: Retry exhaustion writes dead-letter records.
- [ ] **PASS**: Dead-letter replay and manual-redrive paths are available and test-backed.
- [ ] **PASS**: Admin APIs expose completion, dead-letter, duplicate summary, reliability summary.

Evidence:
- `tests/test_jira_integration.py::test_jira_send_decision_is_idempotent_for_retries`
- `tests/test_jira_integration.py::test_jira_send_decision_writes_dlq_after_retry_exhaustion`
- `tests/test_servicenow_integration.py::test_servicenow_send_decision_is_idempotent_for_duplicate_retry`
- `tests/test_servicenow_integration.py::test_servicenow_send_decision_writes_dlq_after_retry_exhaustion`
- `tests/test_integration_reliability_durability_evidence.py`
- `tests/test_api.py::test_outbound_admin_*`

### 5) Replayability + bundle/version visibility
- [ ] **PASS**: Successful Jira + ServiceNow webhook responses include top-level `policy_bundle` (`bundle_name`, `version`, `integrity_sha256`).
- [ ] **PASS**: `supported_contract` includes normalization + decision artifact hashes and connector identity.
- [ ] **PASS**: Confidence matrix artifact is generated and drift-checked in CI.

Evidence:
- `tests/test_supported_integrations_e2e.py`
- `tests/test_integration_confidence_matrix.py`
- `docs/artifacts/integrations/jira_servicenow_confidence_matrix.json`

## Operational runbook links
- Jira runbook: `docs/integrations/JIRA.md`
- ServiceNow runbook: `docs/integrations/SERVICENOW.md`
- Reliability/admin operations: `docs/OPERATIONS.md`

## Release decision
- **READY**: All gates marked PASS with linked evidence.
- **NOT READY**: Any gate missing evidence, failing tests, or unresolved fail-closed behavior in supported path.
