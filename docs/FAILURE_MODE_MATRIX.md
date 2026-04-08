# Failure Mode Matrix (Deterministic Governance)

This matrix defines deterministic failure handling contracts and CI-enforceable tests.

## Deterministic defaults

SENA uses **fail-closed** behavior by default:

- malformed/unknown configuration and payloads are rejected,
- missing required evidence blocks decisions that require that evidence,
- policy ambiguity or conflict escalates deterministically,
- audit integrity failures are never silently ignored.

All API failures should return the stable machine-readable envelope:

```json
{
  "error": {
    "code": "stable_error_code",
    "message": "stable message",
    "request_id": "req_...",
    "timestamp": "RFC3339",
    "details": {"...": "..."}
  }
}
```

## CI enforcement matrix

| Failure class | Deterministic expected behavior (fail-closed) | Error contract (stable) | CI test case definition |
|---|---|---|---|
| **Malformed inputs** (invalid JSON, wrong types, bad enum values, malformed mappings/policies) | Reject request/load before evaluation; no side effects; response/body shape remains stable across retries. | API: `error.code` in (`validation_error`, `webhook_mapping_error`, parser-specific stable code). Non-API: typed exception (`PolicyParseError`, `ReplayInputError`). | Use parameterized fixtures with malformed payload variants; assert status code, exact `error.code`, stable `details` keys, and zero writes/emissions. |
| **Partial data** (required fields absent, truncated replay/evidence records, incomplete integration payloads) | Deterministically reject when required fields are missing; never infer/auto-fill required governance fields. | `error.code=validation_error` (API) or typed domain exception with stable message prefix and missing-field list in `details`. | Table-driven tests for each required field omission; assert identical failure on repeated submission and no policy decision artifact emitted. |
| **Integration retries / duplicates** (at-least-once delivery from Jira/ServiceNow/webhooks) | First accepted event processed once; duplicate delivery returns deterministic duplicate acknowledgment and no duplicate side effects. | Stable duplicate codes (for example `jira_duplicate_delivery`, `servicenow_duplicate_delivery`) or deterministic idempotent marker (`idempotent=true`) in response contract. | Replay same delivery id N times; assert one side effect, N-1 duplicate responses with same code, and monotonic audit chain continuity. |
| **Schema drift** (version mismatch between stored/ingested schema and current runtime expectations) | Reject incompatible schema versions; allow only explicit migration paths; no implicit fallback parsing. | Stable schema/version code (for example `schema_version_unsupported` / migration validation error), with `details.expected_version` + `details.actual_version`. | Create fixtures for old/new/unknown versions; assert supported versions pass, unsupported versions fail with exact code and explicit version details. |
| **Policy conflicts** (simultaneous allow/deny, inviolable conflicts, precedence ambiguity) | Resolve via documented precedence deterministically; if unresolved or inviolable conflict, escalate/block deterministically. | Stable conflict code (for example `policy_conflict` or existing escalation/block code) with `details` containing implicated rules and precedence path. | Construct policy packs with intentional conflicts; assert same decision outcome and same conflict metadata across repeated evaluations. |
| **Missing evidence** (required approvals/attestations/provenance absent at decision or promotion time) | Block or escalate (per policy) when evidence requirements are unmet; never silently downgrade required evidence gates. | Stable evidence code (for example `missing_required_evidence`) with `details.required` and `details.missing`. | Evaluate/promote scenarios with required evidence removed; assert deterministic block/escalate outcome and exact missing-evidence contract. |
| **Audit corruption scenarios** (tampered hash chain, missing segment, lock/state mismatch) | Verification fails deterministically; strict mode blocks startup/operation; non-strict mode returns explicit invalid verification result without repairing silently. | Verify API: `valid=false` + stable verification error list; strict startup path: explicit `RuntimeError` / startup failure signal. | Corrupt stored audit record/hash pointer in fixture; run verification/startup checks; assert deterministic failure classification and no silent recovery. |

## CI implementation notes

- Prefer parameterized tests so each row above maps to one or more stable test IDs.
- Assert **error codes and details keys**, not only human-readable messages.
- Add regression fixtures whenever introducing new failure classes or error codes.
- Any contract change must update this matrix and associated tests in the same change.
