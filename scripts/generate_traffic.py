#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import time
import urllib.error
import urllib.request
from collections import deque
from typing import Any


def _post_json(url: str, payload: dict[str, Any], timeout: float = 2.0) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def _decision_payload(blocked: bool) -> dict[str, Any]:
    amount = random.randint(500, 25000)
    return {
        "action_type": "approve_vendor_payment",
        "attributes": {
            "amount": amount,
            "vendor_verified": not blocked,
            "source_system": "investor-demo",
        },
        "facts": {"risk_score": round(random.uniform(0.01, 0.95), 3)},
    }


def run(base_url: str, verify_probability: float) -> None:
    evaluate_url = f"{base_url.rstrip('/')}/v1/evaluate"
    verify_url = f"{base_url.rstrip('/')}/v1/audit/verify/tree"
    recent_decisions: deque[str] = deque(maxlen=500)

    interval_seconds = 0.1
    print(
        "Generating traffic at 10 decisions/second. Press Ctrl+C to stop.",
        flush=True,
    )

    while True:
        started = time.monotonic()
        should_block = random.random() < 0.05

        try:
            response_payload = _post_json(evaluate_url, _decision_payload(should_block))
            decision_id = response_payload.get("decision_id")
            if isinstance(decision_id, str):
                recent_decisions.append(decision_id)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"[traffic] evaluation error: {exc}", flush=True)

        if recent_decisions and random.random() < verify_probability:
            target = random.choice(tuple(recent_decisions))
            try:
                # Intentionally sends non-canonical proof material occasionally to
                # exercise verification request/failure telemetry.
                _post_json(
                    verify_url,
                    {
                        "decision_id": target,
                        "merkle_proof": ["bad-proof-fragment"],
                        "expected_root": "bad-root",
                    },
                )
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                print(f"[traffic] verification error: {exc}", flush=True)

        elapsed = time.monotonic() - started
        sleep_for = max(0.0, interval_seconds - elapsed)
        time.sleep(sleep_for)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate continuous SENA demo traffic")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="SENA API base URL",
    )
    parser.add_argument(
        "--verify-probability",
        type=float,
        default=0.2,
        help="Probability of issuing a merkle proof verification per decision",
    )
    args = parser.parse_args()

    verify_probability = min(max(args.verify_probability, 0.0), 1.0)
    run(base_url=args.base_url, verify_probability=verify_probability)


if __name__ == "__main__":
    main()
