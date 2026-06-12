# Supported vs Experimental Inventory

Date: 2026-04-23  
Scope: docs, examples, scripts, and API surface that influence operator trust and onboarding.

## Product truth (default path)

SENA's supported path is intentionally narrow:

1. ingest Jira or ServiceNow approval events,
2. normalize into one deterministic policy context,
3. evaluate against versioned bundles,
4. emit machine-actionable outcomes and replayable audit evidence.

Anything outside that path is intentionally demoted from default onboarding.

## Classification pass

### Supported (default operator flow)

- `README.md`
- `docs/INDEX.md`
- `docs/FLAGSHIP_WORKFLOW.md`
- `docs/CONTROL_PLANE.md`
- `docs/OPERATIONS.md`
- `docs/integrations/JIRA.md`
- `docs/integrations/SERVICENOW.md`
- `examples/flagship/`
- `examples/design_partner_reference/`
- `examples/basic_usage.py`
- `examples/gated_promotion_flow.sh`
- `scripts/check_design_partner_ready.py`
- `scripts/generate_evidence_pack.py`
- `scripts/generate_integration_pilot_pack.py`
- `scripts/verify_policy_registry.py`
- `/v1/integrations/jira/webhook`
- `/v1/integrations/servicenow/webhook`

### Experimental (implemented, non-default)

- `docs/EXPERIMENTAL_INDEX.md`
- `docs/COOKBOOK.md`
- `scripts/load_test.py`
- `scripts/generate_traffic.py`
- `/v1/integrations/webhook`
- `/v1/integrations/slack/interactions`

Runtime gating:
- `development`: both routes are registered by default.
- `pilot`/`production`: both routes are absent by default.
- explicit override: `SENA_ENABLE_EXPERIMENTAL_ROUTES=true`.

### Demo/labs (useful, non-contractual)

- `docs/LABS.md`
- `docs/labs/*`
- `docs/blog/langchain_integration.md`
- `examples/k8s_admission_demo/`
- `examples/langchain_demo/`
- `scripts/benchmark_embedded_rules_vs_sena.py`

### Legacy

- `docs/archive/legacy_vision.md`
- `docs/THIRTY_DAY_WEDGE_PLAN.md`
- unversioned API compatibility endpoints (`/health`, `/evaluate`, `/bundle`)

### Remove from default flow (not delete)

- README default install mention of LangChain extras.
- README first CLI command that referenced demo scenario fixtures instead of flagship workflow assets.

## Coherence actions applied

1. README now points to this inventory and keeps the first CLI command on flagship assets.
2. README default install no longer leads with experimental LangChain extras.
3. API integration route summaries and response headers explicitly label supported vs experimental surfaces.
4. `product_surface_inventory.yaml` now includes scripts and explicit demotion/remove recommendations.

## Promotion rule

A surface can move from experimental/demo to supported only when all are true:

1. deterministic fixtures exist,
2. pass/fail operational runbook exists,
3. support status is reflected in README + docs index + inventory,
4. supported API/CLI path has explicit compatibility expectations.
