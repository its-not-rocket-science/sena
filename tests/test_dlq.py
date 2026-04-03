from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from sena.api.app import create_app
from sena.api.config import ApiSettings


def _settings(tmp_path):
    return ApiSettings(
        policy_dir="src/sena/examples/policies",
        bundle_name="enterprise-demo",
        bundle_version="2026.03",
        processing_sqlite_path=str(tmp_path / "runtime.db"),
    )


def test_failed_evaluate_is_written_to_dlq_and_retryable(tmp_path) -> None:
    app = create_app(_settings(tmp_path))
    client = TestClient(app)

    def _boom(*args, **kwargs):
        raise RuntimeError("transient failure")

    app.state.engine_state.processing_service.process_evaluate = _boom

    fail = client.post(
        "/v1/evaluate",
        json={
            "action_type": "approve_vendor_payment",
            "attributes": {"vendor_verified": True},
        },
    )
    assert fail.status_code == 400

    dlq = client.get("/v1/admin/dlq")
    assert dlq.status_code == 200
    assert dlq.json()["items"]

    app.state.engine_state.processing_service.process_event = lambda event: {"ok": True}
    retry = client.post("/v1/admin/dlq/retry")
    assert retry.status_code == 200
    assert retry.json()["retried"] >= 1
