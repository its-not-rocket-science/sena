# SENA project status

Status: alpha product prototype.

SENA is a deterministic policy-enforcement and governance engine for AI-assisted enterprise workflows.

It evaluates high-risk workflow actions against versioned policy bundles and returns a deterministic decision with machine-readable traces for audit, replay, and operational review.

## Implemented in the supported path

The supported path lives under `src/sena/*` and includes:

- deterministic policy parsing, validation, and evaluation;
- structured decision traces and provenance metadata;
- bundle lifecycle metadata and promotion validation endpoints;
- simulation and diff endpoints for impact analysis;
- Jira and ServiceNow normalisation and webhook evaluation paths;
- tamper-evident JSONL audit chain and verification endpoint;
- API and CLI coverage for evaluate, batch evaluate, simulation, replay drift, diff, and bundle lifecycle workflows.

## Not production-complete yet

SENA does not yet provide:

- transactional multi-tenant control plane;
- built-in RBAC/OIDC administration plane;
- replicated or WORM audit storage;
- asynchronous long-running simulation job orchestration;
- full policy authoring UI;
- collaborative approval workflows.

## Product boundary

Supported:

- `src/sena/policy/*`
- `src/sena/engine/*`
- `src/sena/api/*`
- `src/sena/cli/*`

Not part of the supported product path:

- `sena.legacy.*`
- `src/sena/legacy/*`
- compatibility shims that proxy to legacy code unless explicitly documented.

## How visitors should read this repository

SENA is best understood as a serious alpha: enough has been implemented to demonstrate the operating model, but the enterprise control plane is not complete.

The most important idea is not “another workflow tool”. It is reproducible governance: decisions should be explainable, replayable, and tied to explicit policy versions.
