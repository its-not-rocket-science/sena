# SENA Readiness Model

This document is a capability-readiness map for the supported SENA path (`src/sena/*` with Jira + ServiceNow decisioning).

It separates three questions:
1. What is implemented now.
2. What is suitable for pilot deployments.
3. What is not yet production-grade.

Use this document as the source of truth for maturity claims. If a capability is not listed as pilot-ready here, treat it as alpha or incomplete.

## What is implemented now

Implemented means code paths and docs exist in this repository and are exercised by tests/examples.

- Deterministic policy evaluation and replay contract for normalized approvals.
- Jira and ServiceNow inbound webhook normalization and decision evaluation routes.
- Versioned policy bundle lifecycle primitives (validation, simulation, promotion-oriented workflows).
- Audit evidence primitives including hash-linked records and verification services.
- API and CLI surfaces for evaluation, integrations, and policy operations.
- Basic reliability primitives (for example retries/DLQ patterns and persistence abstractions) in alpha form.

## What is suitable for pilots

Pilot-ready means bounded-scope deployments where operator expectations and controls are explicit.

Suitable pilot profile:
- Single organization or tightly controlled small multi-tenant cohort.
- Jira + ServiceNow approval decisioning as the primary integration path.
- Deterministic outcomes + replayable evidence used for governance reviews.
- Named operators with runbooks for migrations, backup/restore, and incident handling.
- Explicit acceptance that some platform controls are procedural or externally provided.

Pilot usage assumptions:
- Identity and authorization controls are integrated with deployment environment controls, not fully provided by SENA alone.
- Audit durability is adequate for pilot evidence and replay, but not a substitute for immutable enterprise archival systems.
- Concurrency and throughput targets are validated against your expected traffic envelope before rollout.

## What is not yet production-grade

Not production-grade means major platform capabilities still require significant implementation or external systems.

- Full enterprise IAM posture: complete OIDC/SSO integration model, fine-grained RBAC, and admin lifecycle UX are not complete as a packaged platform.
- Enterprise tenancy: strict hard multi-tenant isolation and tenant administration controls require further hardening.
- Tamper-resistant audit durability at enterprise compliance levels (for example WORM-native replicated archival guarantees) is not fully built in.
- Large-scale async orchestration and workload management for long-running simulations/evaluations is incomplete.
- Deep connector ecosystem breadth and enterprise-grade adapter lifecycle tooling are incomplete beyond Jira + ServiceNow focus.
- End-to-end SRE-grade operability (HA defaults, autoscaling patterns, exhaustive observability baselines, and recovery automation) requires additional work.
- Compliance guarantee envelope is incomplete: SENA can provide evidence artifacts, but does not by itself establish full regulatory compliance.

## Capability readiness matrix

| Capability area | Implemented now | Suitable for pilots | Not yet production-grade |
| --- | --- | --- | --- |
| Authn/Authz | API surfaces, integration endpoints, and runtime boundaries are implemented. | Works in controlled deployments where external identity, network boundaries, and operator controls are defined. | Full enterprise SSO/OIDC integration depth, fine-grained RBAC policy model, and mature admin UX are incomplete. |
| Tenancy | Data and policy handling patterns exist for scoped usage. | Usable for single-tenant or tightly managed low-cardinality tenants. | Strong hard multi-tenant isolation, delegated tenant administration, and broad tenant lifecycle tooling need further work. |
| Audit durability | Hash-linked audit artifacts and verification primitives are implemented. | Sufficient for replay/evidence in pilots with disciplined backup and retention operations. | Native immutable replicated archival guarantees (for strict evidentiary/compliance regimes) are incomplete. |
| Scale and concurrency | Core engine/API execution and concurrency paths are implemented and test-covered. | Appropriate for bounded throughput validated by pilot load tests. | Large-scale multi-region throughput envelopes, autoscaling defaults, and strict performance SLO hardening need additional engineering. |
| Async execution | Current runtime supports synchronous decisioning paths and supporting services. | Acceptable when workloads are short-lived and operationally supervised. | Robust built-in async orchestration for heavy/long-running jobs is not complete. |
| Connector depth | Jira and ServiceNow connectors are implemented as supported path. | Strong fit when approval control-plane use cases are centered on Jira + ServiceNow. | Broad marketplace-level connector coverage and uniformly hardened connector lifecycle tooling are incomplete. |
| Operations and observability | Operational docs, metrics/logging hooks, and reliability services exist. | Works with dedicated operators using explicit runbooks and environment-level monitoring. | Turnkey enterprise operations package (HA reference profiles, automated remediations, complete SLO instrumentation defaults) is not complete. |
| Recovery and compliance guarantees | Backup/restore and evidence-generation capabilities are implemented. | Pilot-grade recovery posture is achievable with tested procedures and explicit RTO/RPO expectations. | Full compliance guarantees and audited DR certifications are not provided by SENA alone and require additional controls/work. |

## Terminology

- **Implemented now**: present in code/docs and usable in the supported path.
- **Suitable for pilots**: usable with bounded risk, clear assumptions, and operator controls.
- **Not yet production-grade**: requires substantial additional engineering and/or external control systems before broad enterprise production claims are defensible.
