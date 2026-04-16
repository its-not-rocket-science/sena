#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "src"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from tests.replay_corpus.helpers import (
    evaluate_corpus_cases,
    evaluate_duplicate_delivery_cases,
    write_baseline,
)


def main() -> None:
    payload = {
        "schema": "sena.replay_corpus.baseline.v1",
        "cases": evaluate_corpus_cases(),
        "duplicate_delivery": evaluate_duplicate_delivery_cases(),
    }
    write_baseline(payload)
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
