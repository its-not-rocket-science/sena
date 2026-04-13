# Product Surface Reclassification Report

Date: 2026-04-13

## Scope tightening summary

Supported product is now consistently framed as:
**deterministic Jira + ServiceNow approval decisioning with replayable audit evidence**.

## Reclassified items

### Moved out of default reader path

- `docs/COOKBOOK.md` → experimental index only.
  - Why: starts with LangChain + K8s recipes, which are non-supported.
- `docs/LABS.md`, `docs/labs/*`, `docs/blog/langchain_integration.md` → non-default experimental/labs set.
  - Why: investor and exploratory content is non-contractual.
- `examples/k8s_admission_demo/`, `examples/langchain_demo/` → labs/demo only.
  - Why: demos are useful, but not supported commitments.
- `docs/THIRTY_DAY_WEDGE_PLAN.md` → legacy/historical.
  - Why: contains superseded positioning.

### Kept prominent as supported

- `README.md`, `docs/INDEX.md`, `docs/CONTROL_PLANE.md`, `docs/ARCHITECTURE.md`
- `docs/integrations/JIRA.md`, `docs/integrations/SERVICENOW.md`
- `examples/design_partner_reference/`, `examples/basic_usage.py`, `examples/gated_promotion_flow.sh`
- Supported packages and routes documented in `product_surface_inventory.yaml`

## Consistency updates

- Package metadata description now matches supported product scope.
- API OpenAPI title/description now reflects Jira + ServiceNow supported depth.
- Deployment guide now avoids demo-first wording and points demo content to the experimental index.
