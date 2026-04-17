# SENA Positioning: What It Is (and Is Not)

## One-sentence positioning

SENA is a deterministic approval-decision engine for Jira and ServiceNow workflows, optimized for replayable evidence, auditability, and human-review escalation contracts.

## What SENA does best

SENA is strongest when teams need to make **repeatable allow/block/escalate decisions** on operational approval events and prove those decisions after the fact.

Core strengths:

1. **Approval-event normalization for operational systems**
   - Normalizes Jira and ServiceNow events into one policy context shape.
   - Lets one policy bundle evaluate equivalent approvals across both systems.

2. **Deterministic policy evaluation and replay**
   - Same normalized input + same bundle version => same canonical outcome.
   - Replay supports regression control, incident reconstruction, and change verification.

3. **Audit-first evidence chain**
   - Emits canonical replay artifacts, review packages, and hash-linked audit records.
   - Makes post-incident and compliance workflows operational instead of ad hoc.

4. **Escalation as a first-class outcome**
   - Not just allow/deny; explicit `ESCALATE_FOR_HUMAN_REVIEW` is part of the contract.
   - Supports realistic governance workflows where ambiguity is expected.

## Where OPA/Cedar-style engines are a better fit

OPA and Cedar-style engines are often the better choice when the primary problem is **general-purpose authorization policy evaluation** across many services.

Use OPA/Cedar-style engines when you need:

- Broad, low-level authorization checks (for example per-request API authorization).
- Tight embedding into service meshes, gateways, or microservice auth middleware.
- A generic policy runtime without SENA’s opinionated evidence/replay workflow model.
- Large-scale ABAC/RBAC policy distribution where approval-event normalization is not central.

In short: if your core challenge is universal authorization enforcement, start with OPA/Cedar-style systems. If your core challenge is deterministic approval governance with replayable evidence in Jira/ServiceNow workflows, SENA is the sharper tool.

## Why deterministic replay + audit + approval normalization is the wedge

Many teams can evaluate policy once; fewer can reliably answer:

- *“Would we make the same decision again?”*
- *“What exact policy version and normalized facts drove this result?”*
- *“Can we prove this in an auditor-friendly artifact chain?”*

SENA’s wedge is the combined contract:

- **Normalized approval events** across Jira/ServiceNow,
- **Deterministic replay semantics** for decision verification, and
- **Audit/evidence artifacts** designed for operational and compliance review.

The combination matters more than any individual feature. Generic policy engines can be extended to emulate parts of this, but SENA treats it as the default product path.

## What SENA is not

SENA should **not** be described as:

- A general AI governance platform.
- A universal policy engine for every authorization domain.
- A complete enterprise control plane for all governance workflows.

Technically accurate framing:

- SENA is an alpha system with a deliberately narrow supported path.
- Its productized depth is deterministic approval decisioning + replayable evidence for Jira and ServiceNow workflows.
- Other surfaces in the repository may exist, but they are not equivalent to a broad “AI governance platform” claim.

## Messaging guardrails (for docs, demos, and external communication)

Preferred language:

- “Deterministic approval decisioning engine.”
- “Replayable audit evidence for Jira and ServiceNow approval workflows.”
- “Opinionated governance runtime for allow/block/escalate outcomes.”

Avoid language that implies:

- End-to-end enterprise governance coverage across all systems.
- General AI model-risk governance or model lifecycle governance.
- Connector parity beyond supported integration contracts.
