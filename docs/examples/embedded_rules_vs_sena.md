# Embedded Workflow Rules vs. Centralized SENA Evaluation (Reproducible Governance Benchmark)

This demo is a **governance/change-control benchmark** (not a throughput benchmark) that uses repository examples to compare:

1. policy change impact visibility,
2. replayability,
3. auditability,
4. cross-system reuse, and
5. promotion governance.

It intentionally avoids synthetic performance claims.

## Data used from this repo

- Design-partner candidate/active bundles:
  - `examples/design_partner_reference/policy_bundles/candidate/`
  - `examples/design_partner_reference/policy_bundles/active/`
- Design-partner simulation + integration fixtures:
  - `examples/design_partner_reference/fixtures/simulation_scenarios.json`
  - `examples/design_partner_reference/fixtures/jira_event_*.json`
  - `examples/design_partner_reference/fixtures/servicenow_event_*.json`
- Real integration mappings:
  - `examples/design_partner_reference/integration/jira_mapping.yaml`
  - `examples/design_partner_reference/integration/servicenow_mapping.yaml`

## Run

From repository root:

```bash
PYTHONPATH=src python scripts/benchmark_embedded_rules_vs_sena.py \
  --output-dir docs/examples/artifacts/embedded_rules_vs_sena \
  --clean
```

## Produced artifacts

- `summary.json`: top-level result summary.
- `sena_policy_change_impact.json`: centralized simulation impact report (`simulate_bundle_impact`).
- `embedded_policy_change_impact.json`: representative per-workflow baseline output.
- `cross_system_reuse.json`: same SENA bundle evaluated across Jira + ServiceNow mapped proposals.
- `sena/replayability.json`: deterministic replay evidence (`decision_hash` stable on replay).
- `sena/audit_summary.json` + `sena/audit/sena_audit.jsonl`: tamper-evident audit summary + records.
- `embedded_replayability_placeholder.json`: representative embedded log shape (without bundle identity / chain hash).
- `promotion_governance.json`: lifecycle gate behavior with and without required artifacts.

## How each comparison is evidenced

### 1) Policy change impact visibility

- Evidence files:
  - `sena_policy_change_impact.json`
  - `embedded_policy_change_impact.json`
- What to inspect:
  - SENA provides one grouped change-impact artifact with changed-scenario counts and grouping dimensions.
  - Embedded baseline output is per-workflow and does not include the centralized grouped impact artifact.

### 2) Replayability

- Evidence file: `sena/replayability.json`
- What to inspect:
  - `deterministic_replay=true` rows where first/second evaluation share outcome + `decision_hash`.
  - persisted bundle metadata (`bundle_version`, `bundle_integrity_sha256`) on each row.
- Baseline comparator:
  - `embedded_replayability_placeholder.json` shows representative embedded workflow log rows lacking portable bundle identity fields.

### 3) Auditability

- Evidence files:
  - `sena/audit/sena_audit.jsonl`
  - `sena/audit_summary.json`
- What to inspect:
  - `audit_summary.valid=true` demonstrates intact audit-chain verification for generated records.

### 4) Cross-system reuse

- Evidence file: `cross_system_reuse.json`
- What to inspect:
  - `source_systems` includes Jira and ServiceNow fixtures.
  - both are evaluated under one policy bundle identity (`single_bundle`).

### 5) Promotion governance

- Evidence file: `promotion_governance.json`
- What to inspect:
  - `sena_with_required_artifacts.valid=true`.
  - `sena_without_required_artifacts.valid=false` with explicit gate errors.
  - baseline entry documents that embedded workflow edits have no repo-level lifecycle validator and rely on out-of-band process.

## Interpreting the result

This benchmark demonstrates differentiation via generated evidence artifacts (simulation reports, replay records, audit-chain verification, and promotion-gate outcomes), not slogans. Re-run the command above to regenerate every artifact.
