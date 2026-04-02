# Pilot Acceptance Criteria and Evidence Bundle

This document defines SENA's explicit **"good enough for pilot"** bar and the reproducible evidence required to demonstrate it.

## Chosen pilot use case

High-risk enterprise change approvals that originate from Jira and ServiceNow events, are normalized into one decision model, and are promoted through controlled policy bundle releases.

## Pilot-readiness acceptance criteria

A pilot candidate is accepted only when all criteria below pass in a generated evidence bundle.

| Criterion | Threshold | Why it matters | Evidence artifact |
|---|---:|---|---|
| Deterministic replay success rate | `1.00` (100%) | Confirms identical inputs replay to identical outcomes and decision hashes. | `benchmark/sena/replayability.json` |
| Promotion gate coverage | `>= 0.90` | Confirms release control enforces both allow and deny gate paths. | `benchmark/promotion_governance.json` |
| Audit verification pass rate | `1.00` | Confirms tamper-evident chain verification is intact for generated records. | `benchmark/sena/audit_summary.json` |
| API error-shape stability | `1.00` | Confirms API error contract tests are stable for integrators. | `checks/api_error_shape_stability.json` |
| Restore drill success | `1.00` | Confirms disaster-recovery workflow is executable and passing. | `checks/restore_drill.json` |
| Integration fixture coverage | `fixtures >= 5` and `systems >= 2` | Confirms pilot evidence spans both supported systems (Jira + ServiceNow). | `benchmark/cross_system_reuse.json` |

## Benchmark evidence dimensions (SENA vs embedded workflow rules)

The generated benchmark evidence must include all five dimensions below for the selected use case:

1. **Explainability**: deterministic review package artifacts with matched rules and rationale.
2. **Policy portability**: one bundle reused across Jira + ServiceNow mapped fixtures.
3. **Release control**: promotion validator pass/fail behavior based on required artifacts.
4. **Replayability**: stable decision hashes on repeated evaluations.
5. **Audit evidence**: verifiable chain summary + append-only JSONL audit records.

## One-command evidence generation

From repo root:

```bash
make pilot-evidence
```

Equivalent direct script invocation:

```bash
PYTHONPATH=src python scripts/generate_pilot_evidence.py --output-dir docs/examples/pilot_evidence_sample --clean
```

## Output bundle contract

`docs/examples/pilot_evidence_sample/` contains:

- `pilot_acceptance_results.json` (pass/fail summary for all criteria),
- `BENCHMARK_EVIDENCE.md` (narrative benchmark evidence),
- `benchmark/*` (replay, audit, promotion, portability and change-impact artifacts),
- `checks/*` (command-level evidence for API shape stability and restore drills),
- `evidence_pack/*` (deterministic evidence-pack artifacts from reference inputs).

## Pilot release decision rule

SENA is **good enough for pilot** only if:

- `pilot_acceptance_results.json` reports `"all_passed": true`, and
- no criterion is below its documented threshold.

If any criterion fails, pilot promotion is blocked until remediation and evidence regeneration succeed.
