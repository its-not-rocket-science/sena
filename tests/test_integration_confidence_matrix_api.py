from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from sena.api.app import create_app
from sena.api.config import ApiSettings


SERVICENOW_MAPPING = "src/sena/examples/integrations/servicenow_mappings.yaml"


def _settings(**kwargs: object) -> ApiSettings:
    defaults = {
        "policy_dir": "src/sena/examples/policies",
        "bundle_name": "enterprise-demo",
        "bundle_version": "2026.03",
        "enable_api_key_auth": False,
        "api_key": None,
        "api_keys": (),
    }
    defaults.update(kwargs)
    return ApiSettings(**defaults)


def test_servicenow_unsupported_event_is_rejected() -> None:
    app = create_app(_settings(servicenow_mapping_config_path=SERVICENOW_MAPPING))
    client = TestClient(app)
    payload = json.loads(
        Path("tests/fixtures/integrations/servicenow/emergency_change.json").read_text(
            encoding="utf-8"
        )
    )
    payload["event_type"] = "change_approval.completed"

    response = client.post(
        "/v1/integrations/servicenow/webhook",
        json=payload,
        headers={"x-servicenow-delivery-id": "sn-unsupported-event"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "servicenow_unsupported_event_type"
