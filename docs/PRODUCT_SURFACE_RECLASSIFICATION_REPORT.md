# Product Surface Reclassification Report

Date: 2026-04-18

## Scope tightening summary

Supported product is consistently framed as:
**deterministic Jira + ServiceNow approval decisioning with replayable audit evidence**.

## Audit result by surface type

- **Docs:** supported reader path remains `README.md` → `docs/INDEX.md` → `docs/FLAGSHIP_WORKFLOW.md` and integration/operator docs.
- **Examples:** supported flow leads with `examples/flagship/` and `examples/design_partner_reference/`; k8s/langchain remain labs-only.
- **Scripts:** operational governance scripts are supported; load/traffic and benchmark scripts are explicitly non-default.
- **API:** Jira and ServiceNow webhook endpoints are supported; generic webhook and Slack are explicitly experimental.

## Changes made in this pass

1. Added a crisp inventory: `docs/SUPPORTED_VS_EXPERIMENTAL_INVENTORY.md`.
2. Expanded `product_surface_inventory.yaml` to cover scripts and explicit remove/demote recommendations.
3. Updated README to:
   - link to inventory,
   - remove experimental install extras from default install path,
   - use flagship CLI payloads instead of demo scenario fixtures.
4. Updated API route annotations so surface stage is explicit in OpenAPI summaries and response headers.

## Trust-preserving policy

Useful internal assets are retained, but non-supported assets are demoted from the default onboarding path.
