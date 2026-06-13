# SENA

> Deterministic policy engine for Jira and ServiceNow approvals with replayable audit evidence.  
> Status: alpha product prototype.

SENA is a policy-as-code decisioning engine for approval workflows where reproducibility, governance, and auditability matter more than opaque automation.

Given the same normalised input and policy bundle, SENA produces the same decision, reasoning, and audit evidence every time. Decisions can be replayed, verified, and traced back to the exact policy bundle and input that produced them.

## Why SENA?

Most workflow and approval systems answer:

> What decision was made?

SENA is designed to answer:

> Why was this decision made, can we prove it, and can we reproduce it later?

Key capabilities:

- deterministic policy evaluation;
- policy bundle lifecycle management;
- replayable decision evidence;
- hash-linked audit chains;
- Jira and ServiceNow integration;
- promotion workflows with governance controls;
- decision simulation and validation;
- policy-as-code authoring;
- API-first architecture.

## Current scope

The supported path today is:

- Jira approval workflows;
- ServiceNow approval workflows;
- deterministic policy evaluation;
- audit evidence generation;
- policy bundle lifecycle management;
- replay and verification APIs.

Experimental functionality exists in the repository, but is not considered part of the supported path unless explicitly documented otherwise.

See:

- [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md)
- [`docs/INDEX.md`](docs/INDEX.md)
- [`docs/READINESS.md`](docs/READINESS.md)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

## Core concepts

### Policy bundles

Policies are grouped into versioned bundles.

A bundle contains:

- rules;
- invariants;
- metadata;
- compatibility information;
- lifecycle state.

Example lifecycle:

```text
draft
  ↓
candidate
  ↓
approved
  ↓
active
  ↓
deprecated
```

Bundles can be promoted, validated, simulated, rolled back, and audited.

### Deterministic evaluation

Inputs are normalised into canonical action proposals.

SENA then evaluates:

- hard invariants;
- explicit policy rules;
- escalation conditions;
- supporting metadata;
- evidence requirements.

The output is a structured decision such as:

```text
APPROVED
BLOCKED
ESCALATE_FOR_HUMAN_REVIEW
```

## Install

```bash
pip install -e .
pip install -e .[api,dev]
```

## Run tests

```bash
pytest
```

Coverage report target is configured at 80% for the `sena` package.

## CLI quick start

```bash
python -m sena.cli.main   src/sena/examples/scenarios/demo_vendor_payment_block_unverified.json   --json
```

## Policy authoring workflow

```bash
PYTHONPATH=src python -m sena.cli.main policy init ./my-policy-bundle
PYTHONPATH=src python -m sena.cli.main policy validate --policy-dir ./my-policy-bundle
PYTHONPATH=src python -m sena.cli.main policy test   --policy-dir ./my-policy-bundle   --test-file ./my-policy-bundle/tests/policy_tests.json
```

## API quick start

```bash
python -m uvicorn sena.api.app:app --reload
```

Current supported API surface is `/v1/*`.

Useful endpoints include:

- `GET /v1/health`
- `GET /v1/ready`
- `POST /v1/evaluate`
- `POST /v1/integrations/jira/webhook`
- `POST /v1/integrations/servicenow/webhook`
- `POST /v1/simulation`
- `POST /v1/replay/drift`
- `POST /v1/bundle/diff`
- `GET /v1/audit/verify`
- `GET /metrics`

## What SENA is not

SENA is not:

- a formal verification system;
- a general-purpose “safe AI” platform;
- a finished enterprise suite;
- a replacement for Jira or ServiceNow;
- a production-ready multi-tenant control plane.

It is an alpha governance engine focused on deterministic, inspectable approval decisions.

## Licence

MIT — see `LICENSE`.
