import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from sena.api.app import create_app
from sena.api.config import ApiSettings


def _settings(**kwargs):
    defaults = {
        "policy_dir": "src/sena/examples/policies",
        "bundle_name": "enterprise-demo",
        "bundle_version": "2026.03",
        "enable_api_key_auth": False,
        "api_key": None,
        "api_keys": (),
        "audit_sink_jsonl": None,
    }
    defaults.update(kwargs)
    return ApiSettings(**defaults)


def _run_cli_json(payload_path: Path) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = f"src:{env.get('PYTHONPATH', '')}".rstrip(":")
    result = subprocess.run(
        [sys.executable, "-m", "sena.cli.main", str(payload_path), "--json", "--dry-run"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return json.loads(result.stdout)


def _normalize(result: dict) -> dict:
    normalized = json.loads(json.dumps(result, default=str))
    normalized.pop("decision_id", None)
    normalized.pop("decision_hash", None)
    normalized.pop("decision_timestamp", None)
    if isinstance(normalized.get("audit_record"), dict):
        normalized["audit_record"].pop("decision_id", None)
        normalized["audit_record"].pop("timestamp", None)
    return normalized


def test_cli_json_matches_api_evaluate_shape(tmp_path: Path) -> None:
    payload = {
        "action_type": "approve_vendor_payment",
        "request_id": "req-cli-api-consistency",
        "actor_id": "actor-123",
        "actor_role": "finance_analyst",
        "attributes": {"amount": 15000, "vendor_verified": False},
        "facts": {"region": "us-east-1"},
        "strict_require_allow": False,
        "dry_run": True,
    }
    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps(payload), encoding="utf-8")

    cli_json = _run_cli_json(scenario)

    app = create_app(_settings())
    client = TestClient(app)
    api_response = client.post("/v1/evaluate", json=payload)
    assert api_response.status_code == 200

    assert _normalize(cli_json) == _normalize(api_response.json())
