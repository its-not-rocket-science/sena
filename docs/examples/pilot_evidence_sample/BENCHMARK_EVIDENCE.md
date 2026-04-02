# Pilot benchmark evidence: SENA vs embedded workflow rules

Chosen use case: high-risk enterprise change approvals normalized across Jira and ServiceNow.

## Why SENA is better (artifact-backed)

- **Explainability**: `benchmark/sena/review_packages.json` contains deterministic review packages with matched rules and rationale per decision.
- **Policy portability**: `benchmark/cross_system_reuse.json` shows one policy bundle reused across Jira and ServiceNow fixtures.
- **Release control**: `benchmark/promotion_governance.json` demonstrates promotion passes only with required validation evidence and fails without it.
- **Replayability**: `benchmark/sena/replayability.json` records repeated evaluations with stable `decision_hash` values.
- **Audit evidence**: `benchmark/sena/audit_summary.json` and `benchmark/sena/audit/sena_audit.jsonl` provide tamper-evident chain verification.

## Acceptance criteria snapshot

- [PASS] **deterministic_replay_success_rate** — measured `1.00` against threshold `1.00`.
- [PASS] **promotion_gate_coverage** — measured `1.00` against threshold `>= 0.90`.
- [PASS] **audit_verification_pass_rate** — measured `1.00` against threshold `1.00`.
- [PASS] **api_error_shape_stability** — measured `1.00` against threshold `1.00`.
- [PASS] **restore_drill_success** — measured `1.00` against threshold `1.00`.
- [PASS] **integration_fixture_coverage** — measured `fixtures=5, systems=2` against threshold `fixtures >= 5 and systems >= 2`.

Regenerate this bundle with `make pilot-evidence`.
