# SENA Architecture (Supported vs Legacy)

## Supported architecture (current product path)

SENA's supported path is a deterministic compliance engine:

1. **Policy bundle loading** (`sena.policy.parser`)
2. **Policy validation** (`sena.policy.validation`)
3. **Safe condition interpretation** (`sena.policy.interpreter`)
4. **Deterministic evaluation + precedence** (`sena.engine.evaluator`)
5. **Outputs for operators and systems** (`sena.cli.main`, `sena.api.app`)

## Core components

- `sena.core.models`: action, rule, trace, reasoning, audit record models
- `sena.policy.*`: parsing, validation, interpreter, operator grammar
- `sena.engine.evaluator`: deterministic policy evaluation
- `sena.engine.explain`: human-readable CLI summaries
- `sena.api.app`: FastAPI service (`/health`, `/bundle`, `/evaluate`)
- `sena.cli.main`: local scenario evaluation

## Decision flow

1. Load policy rules and bundle metadata.
2. Build evaluation context from action attributes + facts.
3. Evaluate each applicable rule via allowed operators only.
4. Apply precedence:
   - inviolable `BLOCK`
   - ordinary `BLOCK`
   - `ESCALATE`
   - default `APPROVED` when no matches
5. Return decision summary + machine-readable audit record.

## Policy DSL

Conditions are structured JSON/YAML objects.

- Logical nodes: `and`, `or`, `not`
- Leaf nodes: `field` + one comparison operator
- Allowed comparison operators: `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `contains`

Unsupported operators are rejected during validation.

## Precedence model

- Inviolable `BLOCK` is absolute.
- If no inviolable block exists, any `BLOCK` leads to `BLOCKED`.
- If no block exists and any `ESCALATE` exists, decision is `ESCALATE_FOR_HUMAN_REVIEW`.
- If no rules match, decision is `APPROVED`.

## Deprecated / legacy architecture

Historical modules are retained under `src/sena/legacy/*` for backward compatibility and reference. They include older orchestrator, production-system, evolutionary, and simulated-LLM paths.

These are **not** the supported enterprise-compliance engine.
