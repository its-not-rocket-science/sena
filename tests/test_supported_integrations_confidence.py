from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from sena.api.app import create_app
from sena.api.config import ApiSettings

from tests.support.supported_integrations import (
    canonical_json_bytes,
    hmac_sha256_hex,
    load_integration_fixture,
)


_GOLDEN_ROOT = Path("tests/fixtures/integrations/golden")


def _settings(**kwargs: Any) -> ApiSettings:
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


def _post_supported_webhook(
    *,
    client: TestClient,
    endpoint: str,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> dict[str, Any]:
    response = client.post(endpoint, json=payload, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    ("connector", "endpoint", "mapping_setting", "fixture_name", "delivery_header"),
    [
        (
            "jira",
            "/v1/integrations/jira/webhook",
            {"jira_mapping_config_path": "src/sena/examples/integrations/jira_mappings.yaml"},
            "supported_valid_issue_updated",
            "x-atlassian-webhook-identifier",
        ),
        (
            "servicenow",
            "/v1/integrations/servicenow/webhook",
            {
                "servicenow_mapping_config_path": "src/sena/examples/integrations/servicenow_mappings.yaml"
            },
            "emergency_change",
            "x-servicenow-delivery-id",
        ),
    ],
)
def test_supported_connector_normalized_contract_matches_golden_snapshot(
    connector: str,
    endpoint: str,
    mapping_setting: dict[str, str],
    fixture_name: str,
    delivery_header: str,
) -> None:
    payload = load_integration_fixture(connector, fixture_name)
    app = create_app(_settings(**mapping_setting))
    client = TestClient(app)

    body = _post_supported_webhook(
        client=client,
        endpoint=endpoint,
        payload=payload,
        headers={delivery_header: f"golden-{connector}-1"},
    )

    snapshot_path = _GOLDEN_ROOT / f"{connector}_normalized_contract.json"
    expected = json.loads(snapshot_path.read_text(encoding="utf-8"))
    canonical = body["normalization"]["canonical_replay_payload"]
    actual = {
        "normalized_event": canonical,
        "minimal_contract": {
            "schema_version": canonical["schema_version"],
            "source_system": canonical["source_system"],
            "source_event_type": canonical["source_event_type"],
            "request_id": canonical["request_id"],
            "requested_action": canonical["requested_action"],
            "actor_id": canonical["actor"]["actor_id"],
            "correlation_key": canonical["correlation_key"],
            "idempotency_key": canonical["idempotency_key"],
        },
    }

    assert actual == expected, (
        f"{connector} normalized contract drifted. "
        f"If intentional, update {snapshot_path}."
    )


@pytest.mark.parametrize(
    ("connector", "endpoint", "mapping_setting", "fixture_name", "delivery_header"),
    [
        (
            "jira",
            "/v1/integrations/jira/webhook",
            {"jira_mapping_config_path": "src/sena/examples/integrations/jira_mappings.yaml"},
            "supported_valid_issue_updated",
            "x-atlassian-webhook-identifier",
        ),
        (
            "servicenow",
            "/v1/integrations/servicenow/webhook",
            {
                "servicenow_mapping_config_path": "src/sena/examples/integrations/servicenow_mappings.yaml"
            },
            "emergency_change",
            "x-servicenow-delivery-id",
        ),
    ],
)
def test_supported_connector_replay_hashes_are_deterministic_across_distinct_deliveries(
    connector: str,
    endpoint: str,
    mapping_setting: dict[str, str],
    fixture_name: str,
    delivery_header: str,
) -> None:
    payload = load_integration_fixture(connector, fixture_name)
    app = create_app(_settings(**mapping_setting))
    client = TestClient(app)

    first = _post_supported_webhook(
        client=client,
        endpoint=endpoint,
        payload=payload,
        headers={delivery_header: f"determinism-{connector}-1"},
    )
    second = _post_supported_webhook(
        client=client,
        endpoint=endpoint,
        payload=payload,
        headers={delivery_header: f"determinism-{connector}-2"},
    )

    assert (
        first["normalization"]["determinism_contract"]["canonical_replay_payload_hash"]
        == second["normalization"]["determinism_contract"]["canonical_replay_payload_hash"]
    ), f"{connector} normalization hash changed across semantically identical deliveries"
    assert (
        first["decision"]["determinism_contract"]["canonical_replay_payload_hash"]
        == second["decision"]["determinism_contract"]["canonical_replay_payload_hash"]
    ), f"{connector} decision hash changed across semantically identical deliveries"


@pytest.mark.parametrize(
    (
        "connector",
        "endpoint",
        "mapping_setting",
        "fixture_name",
        "delivery_header",
        "secret_setting_key",
        "signature_header",
        "error_code",
    ),
    [
        (
            "jira",
            "/v1/integrations/jira/webhook",
            {"jira_mapping_config_path": "src/sena/examples/integrations/jira_mappings.yaml"},
            "supported_valid_issue_updated",
            "x-atlassian-webhook-identifier",
            "jira_webhook_secret",
            "x-sena-signature",
            "jira_authentication_failed",
        ),
        (
            "servicenow",
            "/v1/integrations/servicenow/webhook",
            {
                "servicenow_mapping_config_path": "src/sena/examples/integrations/servicenow_mappings.yaml"
            },
            "emergency_change",
            "x-servicenow-delivery-id",
            "servicenow_webhook_secret",
            "x-sena-signature",
            "servicenow_authentication_failed",
        ),
    ],
)
def test_supported_connector_signature_auth_failure_matrix(
    connector: str,
    endpoint: str,
    mapping_setting: dict[str, str],
    fixture_name: str,
    delivery_header: str,
    secret_setting_key: str,
    signature_header: str,
    error_code: str,
) -> None:
    payload = load_integration_fixture(connector, fixture_name)
    raw_body = canonical_json_bytes(payload)

    app = create_app(
        _settings(
            **mapping_setting,
            **{secret_setting_key: "shared-secret"},
        )
    )
    client = TestClient(app)

    missing = client.post(
        endpoint,
        content=raw_body,
        headers={
            "content-type": "application/json",
            delivery_header: f"auth-missing-{connector}",
        },
    )
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == error_code
    assert missing.json()["error"]["details"]["signature_error"] == "missing_signature"

    invalid = client.post(
        endpoint,
        content=raw_body,
        headers={
            "content-type": "application/json",
            delivery_header: f"auth-invalid-{connector}",
            signature_header: "definitely-not-valid",
        },
    )
    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == error_code
    assert invalid.json()["error"]["details"]["signature_error"] == "invalid_signature"

    valid = client.post(
        endpoint,
        content=raw_body,
        headers={
            "content-type": "application/json",
            delivery_header: f"auth-valid-{connector}",
            signature_header: hmac_sha256_hex("shared-secret", raw_body),
        },
    )
    assert valid.status_code == 200, valid.text


@pytest.mark.parametrize(
    ("connector", "endpoint", "mapping_setting", "fixture_name", "delivery_header"),
    [
        (
            "jira",
            "/v1/integrations/jira/webhook",
            {
                "jira_mapping_config_path": "src/sena/examples/integrations/jira_mappings.yaml",
                "integration_reliability_sqlite_path": "{db_path}",
                "integration_reliability_allow_inmemory": False,
            },
            "supported_valid_issue_updated",
            "x-atlassian-webhook-identifier",
        ),
        (
            "servicenow",
            "/v1/integrations/servicenow/webhook",
            {
                "servicenow_mapping_config_path": "src/sena/examples/integrations/servicenow_mappings.yaml",
                "integration_reliability_sqlite_path": "{db_path}",
                "integration_reliability_allow_inmemory": False,
            },
            "emergency_change",
            "x-servicenow-delivery-id",
        ),
    ],
)
def test_supported_connector_duplicate_suppression_survives_app_restart(
    tmp_path: Path,
    connector: str,
    endpoint: str,
    mapping_setting: dict[str, Any],
    fixture_name: str,
    delivery_header: str,
) -> None:
    db_path = tmp_path / f"{connector}_reliability.sqlite"
    payload = load_integration_fixture(connector, fixture_name)

    resolved_settings = {
        key: (str(db_path) if value == "{db_path}" else value)
        for key, value in mapping_setting.items()
    }

    first_app = create_app(_settings(**resolved_settings))
    first_client = TestClient(first_app)
    first_response = first_client.post(
        endpoint,
        json=payload,
        headers={delivery_header: f"restart-{connector}-1"},
    )
    assert first_response.status_code == 200, first_response.text

    restarted_app = create_app(_settings(**resolved_settings))
    restarted_client = TestClient(restarted_app)
    duplicate_response = restarted_client.post(
        endpoint,
        json=payload,
        headers={delivery_header: f"restart-{connector}-1"},
    )

    assert duplicate_response.status_code == 200
    assert duplicate_response.json()["status"] == "duplicate_ignored"


@pytest.mark.parametrize(
    ("connector", "endpoint", "mapping_setting", "fixture_name", "error_code"),
    [
        (
            "jira",
            "/v1/integrations/jira/webhook",
            {"jira_mapping_config_path": "src/sena/examples/integrations/jira_mappings.yaml"},
            "supported_valid_issue_updated",
            "jira_missing_required_fields",
        ),
        (
            "servicenow",
            "/v1/integrations/servicenow/webhook",
            {
                "servicenow_mapping_config_path": "src/sena/examples/integrations/servicenow_mappings.yaml"
            },
            "emergency_change",
            "servicenow_missing_required_fields",
        ),
    ],
)
def test_supported_connector_rejects_malformed_required_identity_fields(
    connector: str,
    endpoint: str,
    mapping_setting: dict[str, str],
    fixture_name: str,
    error_code: str,
) -> None:
    payload = load_integration_fixture(connector, fixture_name)
    if connector == "jira":
        payload["user"]["accountId"] = ""
    else:
        payload["requested_by"].pop("user_id", None)

    app = create_app(_settings(**mapping_setting))
    client = TestClient(app)
    response = client.post(endpoint, json=payload)

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == error_code
    assert body["error"]["details"]["stage"] == "normalization"
    assert "missing" in body["error"]["details"]["reason"]
