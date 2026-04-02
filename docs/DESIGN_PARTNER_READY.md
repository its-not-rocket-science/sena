# Design Partner Readiness: Executable Checks and Release Gates

This document turns the maturity plan's design-partner goals into concrete, executable release gates.

## What this gate enforces

The release gate is implemented by `scripts/check_design_partner_ready.py` and covers:

1. **Flagship workflows run end-to-end**
2. **Evidence pack generation**
3. **Audit verification**
4. **Simulation gate enforcement**
5. **Backup/restore success**
6. **Replay/drift analysis pass**
7. **Docs completeness for operator onboarding**

## How to run

```bash
python scripts/check_design_partner_ready.py
```

Optional output location:

```bash
python scripts/check_design_partner_ready.py --output-json artifacts/design_partner_readiness.json
```

The script returns:
- exit code `0` when all required checks pass,
- exit code `1` when any required gate fails.

This makes it directly usable in CI release workflows.

## Gate inventory

| Check | Type | Gate | What runs |
|---|---|---|---|
| `flagship_workflows_end_to_end` | executable | required | `pytest tests/test_flagship_workflows.py tests/test_design_partner_reference.py` |
| `evidence_pack_generation` | executable | required | `python scripts/generate_evidence_pack.py --output-dir .design_partner_tmp/evidence_pack --output-zip .design_partner_tmp/evidence_pack.zip --clean` |
| `audit_verification` | executable | required | `pytest tests/test_audit_chain_and_schema.py tests/test_audit_sinks.py` |
| `simulation_gate_enforcement` | executable | required | `pytest tests/test_lifecycle_and_simulation.py` |
| `backup_restore_success` | executable | required | `pytest tests/test_policy_registry_disaster_recovery.py` |
| `replay_drift_analysis` | executable | required | `pytest tests/test_replay_drift.py` |
| `operator_docs_completeness` | structural | required | Verifies required onboarding docs exist, contain expected section keywords, and are linked from `README.md` |

## Failure reporting and remediation hints

The check output is intentionally actionable. On failure, each item prints:

- failing check name,
- gate level,
- command (if executable),
- structured failure details (return code + stdout/stderr tails or doc gaps),
- **remediation hint** for next action.

Example failure shape:

```text
- [FAIL] simulation_gate_enforcement (gate=required)
    command: /usr/bin/python -m pytest tests/test_lifecycle_and_simulation.py
    remediation: Update lifecycle gate logic or simulation fixtures so failing bundles cannot be promoted.
    details: { ... }
```

## Release policy

Design-partner release promotion is allowed only when all required checks pass.

If any required check fails, the release gate result is `FAIL` and promotion must be blocked until remediation is complete and the gate is rerun.
