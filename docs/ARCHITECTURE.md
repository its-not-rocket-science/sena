# SENA Architecture (Supported vs Legacy)

## Coherent product narrative anchor

- **Primary wedge:** deterministic policy decisioning for Jira + ServiceNow approval workflows.
- **Supported integration story:** normalized events from Jira and ServiceNow feed a shared deterministic evaluator and shared evidence pipeline.
- **Experimental bucket:** generic webhook, Slack, LangChain callback, and Kubernetes demo code are non-contractual surfaces.

## Supported architecture (source of truth)

Supported code lives in `src/sena/*`:
1. `sena.policy.*` (parse/validate/interpret)
2. `sena.engine.evaluator` (deterministic evaluation)
3. `sena.api.*` and `sena.cli.*` (runtime surfaces)
4. `sena.integrations.jira` and `sena.integrations.servicenow` (supported integration depth)

Legacy code under `src/sena/legacy/*` is out of supported claims.

## Decision flow

1. Normalize source event to policy context.
2. Evaluate safe conditions/operators.
3. Apply precedence (inviolable block, block, escalate, default).
4. Emit deterministic trace and audit metadata.

## Honest maturity statement

Current state is **alpha**. This repository contains core deterministic and evidence primitives, but not a finished enterprise control-plane experience.

## Non-goals / boundaries

- No claim of broad production-grade connector parity across all demo connectors.
- No claim of formal verification.
- No claim that legacy path behavior defines current product guarantees.

## Strategy conflict marker

Any architecture language that treats Kubernetes demo assets as the flagship integration path conflicts with the current supported-path narrative and should be considered historical.
