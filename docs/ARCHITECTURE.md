# SENA Architecture (supported vs legacy)

Terminology in this document follows README: `supported`, `experimental`, `labs/demo`, and `legacy`.

## Architecture anchor: Jira + ServiceNow first

The supported architecture is built around **deterministic decisioning for Jira + ServiceNow approval workflows**.

Supported flow:
1. Receive Jira/ServiceNow event payloads.
2. Normalize into a shared policy context.
3. Evaluate through the shared deterministic evaluator.
4. Emit deterministic decision artifacts and audit evidence.

This is the contract-backed path. Broader applicability (generic webhook, Slack, LangChain callback, Kubernetes labs/demo assets) is secondary and non-contractual.

## supported architecture (source of truth)

Supported code lives in `src/sena/*`:
1. `sena.policy.*` (parse/validate/interpret)
2. `sena.engine.evaluator` (deterministic evaluation)
3. `sena.api.*` and `sena.cli.*` (runtime surfaces)
4. `sena.integrations.jira` and `sena.integrations.servicenow` (supported integration depth)

Legacy code under `src/sena/legacy/*` is legacy and out of supported claims.

## Decision flow

1. Normalize source event to policy context.
2. Evaluate safe conditions/operators.
3. Apply precedence (inviolable block, block, escalate, default).
4. Emit deterministic trace and audit metadata.

## Honest maturity statement

Current state is **alpha**. The repository contains core deterministic and evidence primitives, but not a finished enterprise control-plane experience.

## Non-goals / boundaries

- No claim of broad production-grade connector parity across all demo connectors.
- No claim of formal verification.
- No claim that legacy path behavior defines current product guarantees.

## Strategy conflict marker

Any architecture language that treats Kubernetes labs/demo assets as the flagship integration path is historical.
