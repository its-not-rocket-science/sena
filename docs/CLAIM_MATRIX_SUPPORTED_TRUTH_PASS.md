# Supported Path Documentation Claim Matrix (Truth Pass)

Date: 2026-04-23
Scope: supported path only (`src/sena/*`, Jira + ServiceNow, `/v1/*` supported surfaces).

Backed-by-code scale:
- **yes**: directly implemented on supported path.
- **partial**: implemented with material caveats/limits.
- **no**: not implemented or presented as future-target only.

| Claim | File / section | Backed by code? | Action |
|---|---|---|---|
| SENA is alpha and supported path is deterministic Jira + ServiceNow decisioning with replayable evidence. | `README.md` intro + supported path | yes | keep |
| `docs/READINESS.md` is the single maturity authority. | `README.md`, `docs/INDEX.md`, `docs/CONTROL_PLANE.md`, `docs/ARCHITECTURE.md` | yes | keep (standardized references) |
| Experimental routes are disabled by default in pilot/production and enabled by default in development. | `README.md` integration status; `docs/READINESS.md` runtime route-gating contract | yes (`src/sena/api/app.py`, `src/sena/api/config.py`) | keep |
| Pilot posture does **not** imply full enterprise IAM/tenancy/compliance readiness. | `docs/READINESS.md` not production-grade section | partial | keep (already qualified) |
| Control-plane document describes implemented scope only, not broad readiness claims. | `docs/CONTROL_PLANE.md` maturity statement | yes | keep (qualify wording) |
| Architecture doc reflects supported path boundaries and avoids enterprise-complete claims. | `docs/ARCHITECTURE.md` maturity + non-goals | yes | keep |
| “Why SENA Wins” implies broad market-level superiority. | `docs/WHY_SENA_WINS.md` title + framing | partial | qualify (retitle/reframe to scoped differentiation) |
| Competitive comparison table is valid as scoped pilot positioning only. | `docs/WHY_SENA_WINS.md` competitor table | partial | qualify |
| “Pilot-ready architecture review” is current-state truth. | `docs/PILOT_READY_ARCHITECTURE_REVIEW.md` | no (target-state doc) | qualify (explicitly mark as target-state) |
| “A-grade pilot-ready” is current product status. | `docs/A_GRADE_PILOT_READY.md` | no (rubric/gap doc) | qualify (explicitly aspirational) |
| Internal soundness gap: missing webhook secrets in pilot/prod still allowed. | `docs/INTERNAL_SOUNDNESS_GAP_ANALYSIS.md` section 1 | no (startup now fails in pilot/prod) | qualify/update |
| Internal soundness gap: experimental routes still default-on for pilot/prod. | `docs/INTERNAL_SOUNDNESS_GAP_ANALYSIS.md` section 7 | no (default-off outside development) | qualify/update |
| Internal soundness gap: async jobs have no restart persistence. | `docs/INTERNAL_SOUNDNESS_GAP_ANALYSIS.md` section 5 | partial (sqlite persistence exists, orchestration still in-process) | qualify/update |
| Internal soundness required-now list still includes already-implemented controls. | `docs/INTERNAL_SOUNDNESS_GAP_ANALYSIS.md` prioritization summary | no (list was stale) | qualify/update |

## Net edits applied

1. Added an explicit **canonical maturity statement** section in `docs/READINESS.md` and updated other docs to defer to it.
2. Softened market-language and certainty language in positioning docs to avoid implying enterprise completeness.
3. Converted target-state docs to explicitly say they are plans/rubrics, not current-state claims.
4. Updated internal gap analysis items that were stale versus current supported-path runtime behavior.
