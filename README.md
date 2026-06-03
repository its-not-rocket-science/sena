# SENA

> Deterministic policy engine for Jira and ServiceNow approvals with replayable audit evidence.

SENA is a policy-as-code decisioning engine designed for approval workflows where reproducibility, governance, and auditability matter more than opaque automation.

Given the same normalized input and policy bundle, SENA produces the same decision, reasoning, and audit evidence every time. Decisions can be replayed, verified, and traced back to the exact policy bundle and input that produced them.

---

## Why SENA?

Most workflow and approval systems answer:

> "What decision was made?"

SENA is designed to answer:

> "Why was this decision made, can we prove it, and can we reproduce it later?"

Key capabilities:

- Deterministic policy evaluation
- Policy bundle lifecycle management
- Replayable decision evidence
- Hash-linked audit chains
- Jira and ServiceNow integration
- Promotion workflows with governance controls
- Decision simulation and validation
- Policy-as-code authoring
- API-first architecture

---

## Current Scope

The supported path today is:

- Jira approval workflows
- ServiceNow approval workflows
- Deterministic policy evaluation
- Audit evidence generation
- Policy bundle lifecycle management
- Replay and verification APIs

Experimental functionality exists in the repository but is **not considered part of the supported path** unless explicitly documented otherwise.

See:

- `docs/INDEX.md`
- `docs/READINESS.md`
- `docs/ARCHITECTURE.md`

---

## Core Concepts

### Policy Bundles

Policies are grouped into versioned bundles.

A bundle contains:

- Rules
- Invariants
- Metadata
- Compatibility information
- Lifecycle state

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

---

### Deterministic Evaluation

Inputs are normalized into canonical action proposals.

The evaluator:

1. Loads the active policy bundle
2. Evaluates applicable rules
3. Applies precedence and invariants
4. Produces a deterministic outcome
5. Generates audit evidence

The same inputs and bundle version always produce the same result.

---

### Replayable Evidence

Each decision records:

- Decision ID
- Bundle version
- Matched rules
- Outcome
- Reasoning
- Determinism contract
- Audit chain information

This allows:

- Reproduction
- Investigation
- Verification
- Change impact analysis

---

### Audit Chain

Audit records are hash-linked.

Each record contains:

- Previous chain hash
- Current chain hash
- Decision metadata
- Optional signatures

The chain can be verified later to detect:

- Tampering
- Missing records
- Sequence gaps
- Duplicate decision IDs

---

## Architecture

```text
             ┌────────────────────┐
             │ Jira / ServiceNow  │
             └─────────┬──────────┘
                       │
                       ▼
          ┌──────────────────────────┐
          │ Event Normalization Layer │
          └─────────┬────────────────┘
                    │
                    ▼
          ┌──────────────────────────┐
          │ Deterministic Evaluator  │
          └─────────┬────────────────┘
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
 ┌────────────────┐  ┌─────────────────┐
 │ Policy Bundles │  │ Audit Evidence  │
 └────────────────┘  └─────────────────┘
          │                   │
          ▼                   ▼
 ┌────────────────┐  ┌─────────────────┐
 │ Governance API │  │ Replay / Verify │
 └────────────────┘  └─────────────────┘
```

---

## Supported Integrations

### Jira

Supported capabilities:

- Webhook ingestion
- Event normalization
- Policy evaluation
- Decision delivery
- Reliability tracking
- Dead-letter handling
- Replay support

### ServiceNow

Supported capabilities:

- Webhook ingestion
- Event normalization
- Policy evaluation
- Callback delivery
- Reliability tracking
- Dead-letter handling
- Replay support

---

## API

Versioned API endpoints are exposed under:

```text
/v1/*
```

Examples:

```text
GET  /v1/health
POST /v1/evaluate
GET  /v1/bundle
POST /v1/integrations/jira/webhook
POST /v1/integrations/servicenow/webhook
GET  /v1/audit/verify
```

See OpenAPI documentation:

```text
/docs
```

when running locally.

---

## Example Policy

```yaml
- id: vendor_must_be_verified
  description: Vendor must be verified
  severity: high
  inviolable: true

  applies_to:
    - approve_vendor_payment

  condition:
    vendor_verified: false

  decision: block

  reason: Vendor verification required
```

---

## Development

### Install

```bash
git clone https://github.com/its-not-rocket-science/sena.git

cd sena

pip install -e .
```

### Run Tests

```bash
pytest
```

### Start API

```bash
uvicorn sena.api.app:app --reload
```

---

## Maturity

SENA is currently best described as:

> An alpha-stage deterministic decisioning engine with a supported Jira + ServiceNow approval workflow path.

Implemented today:

- Deterministic evaluation
- Policy lifecycle management
- Audit chain verification
- Replayable evidence
- Jira integration
- ServiceNow integration
- Governance APIs
- Reliability and dead-letter handling

Areas still being hardened:

- Distributed idempotency
- Production deployment profiles
- Stronger step-up authentication
- Durable queueing defaults
- Long-running job persistence
- Multi-tenant isolation

See:

```text
docs/READINESS.md
docs/INTERNAL_SOUNDNESS_GAP_ANALYSIS.md
```

for the current state of the supported path.

---

## Design Principles

SENA prioritizes:

1. Determinism over automation magic
2. Explicit governance over hidden behaviour
3. Replayability over convenience
4. Auditability over opacity
5. Narrow supported scope over broad unsupported claims

---

## Non-Goals

SENA is not:

- A general workflow engine
- A BPMN platform
- A ticketing system
- An IAM platform
- A compliance certification product
- A replacement for Jira or ServiceNow

SENA focuses on deterministic approval decisioning and audit evidence.

---

## License

See `LICENSE`.

---

## Status

Active development.

The recommended path for evaluation is the supported Jira + ServiceNow workflow documented in:

```text
docs/INDEX.md
```
