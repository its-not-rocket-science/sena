# Replay Corpus (Supported Jira + ServiceNow Path)

This repository includes a curated replay corpus for the supported product path so behavior drift is caught by stable baselines, not just ad hoc examples.

## Location

- Corpus manifest: `tests/replay_corpus/cases.json`
- Source fixtures: `tests/replay_corpus/fixtures/`
- Baselines: `tests/replay_corpus/baselines/outcomes.json`
- Tests: `tests/test_replay_corpus.py`
- Refresh helper: `scripts/refresh_replay_corpus.py`

## Scenarios covered

The corpus currently includes:

- simple approval
- block due to policy
- escalation due to missing evidence
- duplicate delivery
- exception overlay
- one Jira mapped case
- one ServiceNow mapped case

## What is asserted

For replay cases we compare:

- outcome
- decision hash
- matched rule ids
- missing fields / missing evidence
- applied exception ids (where relevant)

For duplicate delivery we compare the deterministic integration error contract.

## Making intentional baseline updates

When expected behavior changes intentionally, refresh and review the baseline:

```bash
python scripts/refresh_replay_corpus.py
pytest tests/test_replay_corpus.py
```

The replay corpus tests include readable per-case expected-vs-actual diffs so accidental drift is obvious.
