#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "src"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from tests.replay_corpus.helpers import build_drift_report, refresh_fixture_expectations


def main() -> None:
    updated = refresh_fixture_expectations()
    report = build_drift_report()
    payload = {
        "schema": "sena.replay_refresh_report.v1",
        "updated_fixtures": updated,
        "semantic_drift_summary": report["semantic_drift_summary"],
        "remaining_mismatches": report["mismatches"],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
