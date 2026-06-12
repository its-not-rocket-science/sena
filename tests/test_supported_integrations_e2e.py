from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from sena.api.app import create_app
from sena.api.config import ApiSettings


def _settings(**kwargs) -> ApiSettings:
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


def _json_fixture(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("name", "endpoint", "settings_kwargs", "payload_fixture", "headers"),
    [
        (
            "jira",
            "/v1/integrations/jira/webhook",
            {"jira_mapping_config_path": "src/sena/examples/integrations/jira_mappings.yaml"},
            "tests/fixtures/integrations/jira/low_risk_change_with_cab.json",
            {"x-atlassian-webhook-identifier": "jira-e2e-1"},
        ),
        (
            "servicenow",
            "/v1/integrations/servicenow/webhook",
            {
                "servicenow_mapping_config_path": "src/sena/examples/integrations/servicenow_mappings.yaml"
            },
            "tests/fixtures/integrations/servicenow/emergency_change.json",
            {"x-servicenow-delivery-id": "servicenow-e2e-1"},
        ),
    ],
)
def test_supported_connector_e2e_flow_exposes_replayable_artifacts_and_bundle_visibility(
    name: str,
    endpoint: str,
    settings_kwargs: dict[str, str],
    payload_fixture: str,
    headers: dict[str, str],
) -> None:
    app = create_app(_settings(**settings_kwargs))
    client = TestClient(app)
    payload = _json_fixture(payload_fixture)

    response = client.post(endpoint, json=payload, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "evaluated"
    assert body["policy_bundle"]["bundle_name"] == "enterprise-demo"
    assert body["policy_bundle"]["version"] == "2026.03"
    assert body["supported_contract"]["schema_version"] == "1"
    assert body["supported_contract"]["connector"] == name
    assert body["supported_contract"]["policy_bundle"] == body["policy_bundle"]

    normalization = body["normalization"]
    decision = body["decision"]
    assert normalization["determinism_scope"] == "canonical_replay_payload_only"
    assert decision["determinism_contract"]["scope"] == "canonical_replay_payload_only"
    assert "event_timestamp" not in normalization["canonical_replay_payload"]

    expected_normalization_hash = hashlib.sha256(
        json.dumps(
            normalization["canonical_replay_payload"],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    expected_decision_hash = hashlib.sha256(
        json.dumps(
            decision["canonical_replay_payload"],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert (
        normalization["determinism_contract"]["canonical_replay_payload_hash"]
        == expected_normalization_hash
    )
    assert (
        decision["determinism_contract"]["canonical_replay_payload_hash"]
        == expected_decision_hash
    )
    assert (
        body["supported_contract"]["normalization_artifact"][
            "canonical_replay_payload_hash"
        ]
        == expected_normalization_hash
    )
    assert (
        body["supported_contract"]["decision_artifact"]["canonical_replay_payload_hash"]
        == expected_decision_hash
    )
    assert (
        body["supported_contract"]["decision_artifact"]["decision_hash"]
        == decision["decision_hash"]
    )
    assert (
        body["supported_contract"]["normalization_artifact"]["request_id"]
        == body["normalized_event"]["request_id"]
    )
