from __future__ import annotations

import json
from pathlib import Path

from tests.replay_corpus.helpers import (
    evaluate_corpus_cases,
    evaluate_duplicate_delivery_cases,
    load_baseline,
)


def _pretty(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def test_replay_corpus_matches_baseline() -> None:
    baseline = load_baseline()
    current = evaluate_corpus_cases()

    assert sorted(current) == sorted(
        baseline["cases"]
    ), "Replay corpus case IDs drifted. Refresh baseline intentionally."

    mismatches: list[str] = []
    for case_id in sorted(current):
        expected = baseline["cases"][case_id]
        actual = current[case_id]
        if actual != expected:
            mismatches.append(
                "\n".join(
                    [
                        f"case_id={case_id}",
                        f"expected:\n{_pretty(expected)}",
                        f"actual:\n{_pretty(actual)}",
                    ]
                )
            )

    assert not mismatches, (
        "Replay corpus drift detected. If this is intentional, run "
        "`python scripts/refresh_replay_corpus.py`.\n\n"
        + "\n\n".join(mismatches)
    )


def test_replay_corpus_duplicate_delivery_contract() -> None:
    baseline = load_baseline()
    current = evaluate_duplicate_delivery_cases()

    assert sorted(current) == sorted(
        baseline["duplicate_delivery"]
    ), "Duplicate-delivery replay case IDs drifted. Refresh baseline intentionally."

    mismatches: list[str] = []
    for case_id in sorted(current):
        expected = baseline["duplicate_delivery"][case_id]
        actual = current[case_id]
        if actual != expected:
            mismatches.append(
                "\n".join(
                    [
                        f"case_id={case_id}",
                        f"expected:\n{_pretty(expected)}",
                        f"actual:\n{_pretty(actual)}",
                    ]
                )
            )

    assert not mismatches, (
        "Duplicate-delivery contract drift detected. If intentional, run "
        "`python scripts/refresh_replay_corpus.py`.\n\n"
        + "\n\n".join(mismatches)
    )


def test_replay_corpus_baseline_file_exists() -> None:
    assert Path("tests/replay_corpus/baselines/outcomes.json").exists()
