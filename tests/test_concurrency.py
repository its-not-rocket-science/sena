from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")

from sena.api.app import create_app  # noqa: E402
from sena.api.config import ApiSettings  # noqa: E402


def _settings(audit_path: Path) -> ApiSettings:
    return ApiSettings(
        policy_dir="src/sena/examples/policies",
        bundle_name="enterprise-demo",
        bundle_version="2026.03",
        enable_api_key_auth=False,
        api_key=None,
        api_keys=(),
        audit_sink_jsonl=str(audit_path),
        webhook_mapping_config_path="src/sena/examples/integrations/webhook_mappings.yaml",
        rate_limit_requests=5_000,
        rate_limit_window_seconds=60,
        request_max_bytes=1_048_576,
        request_timeout_seconds=15.0,
    )


async def _post_many(app, endpoint: str, payloads: list[dict[str, object]]) -> list[dict[str, object]]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        responses = await asyncio.gather(*[client.post(endpoint, json=payload) for payload in payloads])
    assert all(resp.status_code == 200 for resp in responses)
    return [resp.json() for resp in responses]


def test_concurrent_webhook_requests_and_no_duplicate_audit_entries(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.jsonl"
    app = create_app(_settings(audit_path))

    payloads: list[dict[str, object]] = []
    for index in range(10):
        payloads.append(
            {
                "provider": "stripe",
                "event_type": "payment_intent.created",
                "payload": {
                    "id": f"evt_{index}",
                    "data": {
                        "object": {
                            "amount": 25_000,
                            "currency": "usd",
                            "metadata": {
                                "vendor_verified": False,
                                "requester_role": "finance_analyst",
                                "requested_by": f"user_{index}",
                            },
                        }
                    },
                },
                "facts": {},
            }
        )

    bodies = asyncio.run(_post_many(app, "/v1/integrations/webhook", payloads))
    decision_ids = [str(body["decision"]["decision_id"]) for body in bodies]
    assert len(decision_ids) == len(set(decision_ids))

    audit_rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    persisted_decision_ids = [str(row["decision_id"]) for row in audit_rows]
    assert len(persisted_decision_ids) == len(set(persisted_decision_ids))


def test_concurrent_evaluate_requests_and_no_duplicate_audit_entries(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.jsonl"
    app = create_app(_settings(audit_path))

    payloads: list[dict[str, object]] = []
    for index in range(50):
        payloads.append(
            {
                "action_type": "approve_vendor_payment",
                "request_id": f"req-{index}",
                "attributes": {
                    "amount": 1000 + index,
                    "vendor_verified": index % 2 == 0,
                    "requester_role": "finance_analyst",
                },
                "facts": {},
            }
        )

    bodies = asyncio.run(_post_many(app, "/v1/evaluate", payloads))
    decision_ids = [str(body["decision_id"]) for body in bodies]
    assert len(decision_ids) == len(set(decision_ids))

    audit_rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    persisted_decision_ids = [str(row["decision_id"]) for row in audit_rows]
    assert len(persisted_decision_ids) == len(set(persisted_decision_ids))


def test_sqlite_write_contention_is_handled_with_timeout_and_retries(tmp_path: Path) -> None:
    db_path = tmp_path / "contention.db"
    with sqlite3.connect(db_path, timeout=1.0) as conn:
        conn.execute("CREATE TABLE writes (id INTEGER PRIMARY KEY AUTOINCREMENT, worker TEXT NOT NULL)")

    start_event = threading.Event()

    def locker() -> None:
        conn = sqlite3.connect(db_path, timeout=1.0)
        try:
            conn.execute("BEGIN EXCLUSIVE")
            conn.execute("INSERT INTO writes(worker) VALUES (?)", ("locker",))
            start_event.set()
            time.sleep(0.35)
            conn.commit()
        finally:
            conn.close()

    def write_with_retry(worker: str) -> None:
        start_event.wait(timeout=1.0)
        attempts = 0
        while True:
            attempts += 1
            try:
                with sqlite3.connect(db_path, timeout=0.1) as conn:
                    conn.execute("INSERT INTO writes(worker) VALUES (?)", (worker,))
                return
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempts >= 8:
                    raise
                time.sleep(0.05 * attempts)

    lock_thread = threading.Thread(target=locker, daemon=True)
    lock_thread.start()

    workers = [f"worker-{index}" for index in range(6)]
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(write_with_retry, worker) for worker in workers]
        for future in futures:
            future.result()

    lock_thread.join(timeout=1.0)

    with sqlite3.connect(db_path, timeout=1.0) as conn:
        count = conn.execute("SELECT COUNT(*) FROM writes").fetchone()[0]
    assert count == 1 + len(workers)
