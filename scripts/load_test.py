#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed


def _request(url: str, payload: dict, timeout: float) -> tuple[bool, float, int]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = int(resp.status)
            ok = 200 <= status < 500
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        ok = 200 <= status < 500
    except Exception:
        status = 0
        ok = False
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return ok, elapsed_ms, status


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    idx = min(len(sorted_values) - 1, int(round((pct / 100.0) * (len(sorted_values) - 1))))
    return sorted_values[idx]


def main() -> int:
    parser = argparse.ArgumentParser(description="Simple load test harness for SENA evaluate endpoint")
    parser.add_argument("--url", default="http://127.0.0.1:8000/v1/evaluate")
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()

    payload = {
        "action_type": "approve_vendor_payment",
        "actor_id": "load-tester",
        "attributes": {"vendor_verified": True, "amount": 1250},
    }

    latencies: list[float] = []
    statuses: dict[int, int] = {}
    success = 0

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(_request, args.url, payload, args.timeout) for _ in range(args.requests)]
        for future in as_completed(futures):
            ok, latency, status = future.result()
            latencies.append(latency)
            statuses[status] = statuses.get(status, 0) + 1
            if ok:
                success += 1

    duration = max(time.perf_counter() - started, 0.001)
    result = {
        "requests": args.requests,
        "concurrency": args.concurrency,
        "duration_seconds": round(duration, 3),
        "throughput_rps": round(args.requests / duration, 2),
        "success_rate": round((success / args.requests) * 100.0, 2),
        "latency_ms": {
            "p50": round(_percentile(latencies, 50), 2),
            "p95": round(_percentile(latencies, 95), 2),
            "p99": round(_percentile(latencies, 99), 2),
        },
        "status_counts": statuses,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
