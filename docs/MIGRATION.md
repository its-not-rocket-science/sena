# Migration Notes: Package Reorganization for Supported Product Path

This migration note documents the package boundary reorganization that makes
supported product paths obvious from layout alone.

## New package map (recommended import roots)

- `sena.core_policy_engine`
- `sena.supported_integrations`
- `sena.runtime`
- `sena.audit_evidence`
- `sena.experimental`

These are organizational entry points that re-export existing modules. Existing
imports keep working.

## Relabeled module boundaries

| Old/low-signal import area | New high-signal import root | Notes |
| --- | --- | --- |
| `sena.policy`, `sena.engine`, `sena.core` | `sena.core_policy_engine` | Supported deterministic engine path. |
| `sena.integrations.jira`, `sena.integrations.servicenow`, `sena.integrations.persistence` | `sena.supported_integrations` | Productized connectors + reliability persistence. |
| `sena.api`, `sena.cli`, `sena.services` | `sena.runtime` | Runtime and operator entry surfaces. |
| `sena.audit`, `sena.evidence_pack`, `sena.verification.attestations` | `sena.audit_evidence` | Audit chain + evidence artifacts and verification. |
| `sena.integrations.webhook`, `sena.integrations.slack`, `sena.integrations.langchain`, `sena.llm`, `sena.evolutionary`, `sena.production_systems`, `sena.orchestrator`, `sena.monitoring` | `sena.experimental` | Explicitly unstable/evaluation-only area. |

## Compatibility and legacy behavior

- Existing module paths remain valid; this change adds higher-signal import roots.
- `sena.legacy` remains intentionally unavailable (importing it still fails).
- Legacy import guardrails continue to live in `sena._legacy_guard` for controlled migration policies.

## Contributor guidance

For new code and docs:

1. Prefer the new package map to explain supported vs experimental scope.
2. Keep implementation modules in existing locations unless a dedicated follow-up
   move is planned with compatibility shims and tests.
3. Treat `sena.experimental` as unstable and outside support commitments.
