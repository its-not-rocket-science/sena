# SENA Enterprise Gap Analysis (alpha baseline)

## Current architecture
- Deterministic policy evaluation pipeline: bundle load -> rule validation -> safe interpreter -> precedence evaluator -> trace/audit output.
- Runtime surfaces: CLI (`sena.cli.main`) and FastAPI API (`sena.api.app`).
- Policy authoring format: YAML/JSON rule files plus optional `bundle.yaml` metadata.
- Legacy research modules are still present under `src/sena/legacy` with compatibility shims.

## Enterprise readiness gaps
- **Configuration/deployment:** no env-based API configuration contract, no container deployment assets, no startup safety gates.
- **API contracts:** unversioned endpoints only, weak error model, limited validation and health semantics.
- **Policy lifecycle:** bundle manifest schema permissive, no deterministic integrity metadata, weak load-time diagnostics.
- **Observability/audit ops:** no structured logs, request correlation IDs, or external audit sink path.
- **Security posture:** no baseline auth guardrail in self-hosted mode, no explicit actor-role metadata path.
- **Testing/developer UX:** test coverage focused on happy path; operations workflows and support boundaries not clear enough.

## Risks
- Misconfiguration risks in production (wrong bundle, missing policy files, silent fallback behavior).
- Integration fragility due to unstable error payloads and unversioned API evolution.
- Audit/compliance review friction from weak operational telemetry and trace export mechanics.
- Buyer confusion caused by legacy code visibility without clear supported-boundary docs.

## Recommended roadmap
1. Harden API runtime config and startup checks; add containerized local deployment path.
2. Introduce versioned API namespace with stable error envelope and readiness endpoint.
3. Strengthen policy bundle manifest and integrity metadata.
4. Add structured logging, request IDs, and JSONL audit sink extension point.
5. Ship minimal self-hosted auth control (API key middleware) and actor metadata handling.
6. Expand parser/evaluator/API tests for malformed bundles and strict modes.
7. Refresh docs for installation, operations, supported-vs-legacy boundary, and alpha limits.

## Out of scope for now
- Multi-tenant control plane, distributed policy service, HA clustering.
- Managed key management, SSO/OIDC integration, full RBAC admin model.
- Formal policy simulation platform/UI and enterprise SIEM integrations.
- Advanced workflow connectors (ERP/ticketing/payment) beyond documented extension seams.
