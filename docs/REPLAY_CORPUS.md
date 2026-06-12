# Replay Corpus (Supported Jira + ServiceNow Path)

This repository includes a high-signal replay corpus for the supported Jira + ServiceNow path so behavior drift is caught by deterministic golden fixtures.

## Location

- Scenario fixtures (golden expectations): `tests/replay_corpus/fixtures/scenarios/*.json`
- Source integration events: `tests/replay_corpus/fixtures/events/*.json`
- Replay harness: `tests/replay_corpus/helpers.py`
- Replay tests: `tests/test_replay_corpus.py`
- Refresh helper: `scripts/refresh_replay_corpus.py`
- Make target: `make replay-refresh`

## Fixture format

Each fixture uses schema `sena.replay_fixture.v1` and contains:

- `case_id` and `description`
- `bundle` identity and version context
  - `path`
  - `expected_name`
  - `expected_version`
- normalized replay input
  - `input.mode = normalized_proposal` with `proposal` + `facts`, or
  - `input.mode = mapped_event` for Jira/ServiceNow-originated events
- `expected` golden outputs
  - `bundle_identity`
  - `outcome`
  - `matched_rules`
  - `missing_fields`
  - `missing_evidence`
  - `decision_hash`
  - `baseline_outcome`
  - `applied_exception_ids`
  - `normalized_proposal` (for mapped normalization verification)

## Scenarios covered

The corpus intentionally stays moderate but high-value and currently includes:

- standard approval
- escalation
- inviolable block
- AI-originated action with missing governance evidence
- schema validation failure
- exception overlay changing baseline outcome
- Jira-originated normalized event
- ServiceNow-originated normalized event

## Drift detection behavior

`tests/test_replay_corpus.py` fails loudly with:

- exact per-field mismatches (`expected` vs `actual`)
- semantic drift summary counters:
  - outcome changes
  - matched-rule set changes
  - missing-field changes
  - decision-hash changes

## Intentional baseline refresh workflow

When policy behavior intentionally changes:

```bash
make replay-refresh
pytest tests/test_replay_corpus.py
```

`make replay-refresh` rewrites each fixture `expected` block using current deterministic evaluation results.

## Maintainer review checklist for replay baseline changes

When reviewing PRs that modify replay fixtures:

1. **Confirm intent**: link each changed fixture to a policy/parser/integration behavior change.
2. **Review semantic impact first**:
   - outcome changes
   - matched rule changes
   - missing field / evidence changes
3. **Treat decision-hash-only drift as suspicious** unless a deterministic input or canonicalization change explains it.
4. **Validate mapped-event normalization deltas** (especially `normalized_proposal` changes) for Jira/ServiceNow fixtures.
5. **Re-run replay tests locally** before approval:
   - `pytest tests/test_replay_corpus.py`
6. **Reject accidental churn**: fixture changes should stay small, specific, and auditable.

Golden data is formatted with sorted keys and stable indentation to remain easy to diff in PRs.
