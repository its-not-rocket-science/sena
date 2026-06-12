from __future__ import annotations

import json

from tests.replay_corpus.helpers import build_drift_report, load_replay_fixtures


def _pretty(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def test_replay_corpus_matches_fixture_expectations() -> None:
    report = build_drift_report()
    mismatches = report["mismatches"]
    summary = report["semantic_drift_summary"]

    assert not mismatches, (
        "Replay corpus drift detected. If intentional, run "
        "`make replay-refresh` (or `python scripts/refresh_replay_corpus.py`).\n\n"
        "Semantic drift summary:\n"
        f"{_pretty(summary)}\n\n"
        "Exact mismatches:\n"
        f"{_pretty(mismatches)}"
    )


def test_replay_fixture_count_is_moderate() -> None:
    fixtures = load_replay_fixtures()
    assert 6 <= len(fixtures) <= 16, (
        "Replay corpus should remain moderate and high-value: expected 6-16 fixtures, "
        f"found {len(fixtures)}"
    )
