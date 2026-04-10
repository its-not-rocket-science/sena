from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sena.integrations.jira import load_jira_mapping_config
from sena.integrations.servicenow import load_servicenow_mapping_config


def build_integration_confidence_matrix(
    *, jira_mapping_path: str | Path, servicenow_mapping_path: str | Path
) -> dict[str, Any]:
    jira_events = sorted(load_jira_mapping_config(str(jira_mapping_path)).routes.keys())
    servicenow_events = sorted(
        load_servicenow_mapping_config(str(servicenow_mapping_path)).routes.keys()
    )

    matrix: dict[str, Any] = {
        "schema_version": "1",
        "integrations": {
            "jira": {
                "supported_event_types": jira_events,
                "verified_failure_modes": [
                    {
                        "error_code": "jira_missing_required_fields",
                        "verified_by": "tests/test_api.py::test_jira_webhook_missing_actor_identity_returns_deterministic_error",
                    },
                    {
                        "error_code": "jira_unsupported_event_type",
                        "verified_by": "tests/test_api.py::test_jira_webhook_unsupported_event_returns_deterministic_error",
                    },
                    {
                        "error_code": "jira_authentication_failed",
                        "details": ["signature_error=invalid_signature", "signature_error=missing_signature"],
                        "verified_by": "tests/test_api.py::test_jira_webhook_signature_verification_rejects_invalid_signature",
                    },
                ],
                "duplicate_delivery_behavior": {
                    "status": "duplicate_ignored",
                    "error_code": "jira_duplicate_delivery",
                    "verified_by": "tests/test_api.py::test_jira_webhook_duplicate_delivery_returns_stable_duplicate_response",
                },
                "signature_verification_support": {
                    "enabled_when_secret_configured": True,
                    "accepted_headers": ["x-sena-signature", "x-hub-signature-256"],
                    "supports_secret_rotation": True,
                    "verified_by": "tests/test_api.py::test_jira_webhook_signature_verification_accepts_current_and_previous_secret",
                },
                "known_unsupported_cases": [
                    {
                        "case": "webhookEvent=jira:comment_created",
                        "error_code": "jira_unsupported_event_type",
                        "verified_by": "tests/test_api.py::test_jira_webhook_unsupported_event_returns_deterministic_error",
                    }
                ],
            },
            "servicenow": {
                "supported_event_types": servicenow_events,
                "verified_failure_modes": [
                    {
                        "error_code": "servicenow_missing_required_fields",
                        "verified_by": "tests/test_api.py::test_servicenow_webhook_missing_actor_identity_returns_deterministic_error",
                    },
                    {
                        "error_code": "servicenow_unsupported_event_type",
                        "verified_by": "tests/test_integration_confidence_matrix_api.py::test_servicenow_unsupported_event_is_rejected",
                    },
                    {
                        "error_code": "servicenow_authentication_failed",
                        "details": ["signature_error=invalid_signature", "signature_error=missing_signature"],
                        "verified_by": "tests/test_api.py::test_servicenow_webhook_signature_verification_rejects_invalid_signature",
                    },
                ],
                "duplicate_delivery_behavior": {
                    "status": "duplicate_ignored",
                    "error_code": "servicenow_duplicate_delivery",
                    "verified_by": "tests/test_api.py::test_servicenow_webhook_duplicate_delivery_returns_stable_duplicate_response",
                },
                "signature_verification_support": {
                    "enabled_when_secret_configured": True,
                    "accepted_headers": ["x-sena-signature", "x-servicenow-signature"],
                    "supports_secret_rotation": True,
                    "verified_by": "tests/test_api.py::test_servicenow_webhook_signature_verification_accepts_current_and_previous_secret",
                },
                "known_unsupported_cases": [
                    {
                        "case": "event_type=change_approval.completed",
                        "error_code": "servicenow_unsupported_event_type",
                        "verified_by": "tests/test_integration_confidence_matrix_api.py::test_servicenow_unsupported_event_is_rejected",
                    }
                ],
            },
        },
    }
    return matrix


def render_integration_confidence_matrix_json(
    *, jira_mapping_path: str | Path, servicenow_mapping_path: str | Path
) -> str:
    payload = build_integration_confidence_matrix(
        jira_mapping_path=jira_mapping_path,
        servicenow_mapping_path=servicenow_mapping_path,
    )
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
