from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sena.integrations.jira import load_jira_mapping_config
from sena.integrations.servicenow import load_servicenow_mapping_config


def _load_confidence_assertions(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("confidence assertions must be a JSON object")
    return payload


def _assert_test_node_exists(node_id: str) -> None:
    file_part, separator, test_name = node_id.partition("::")
    if separator != "::" or not file_part or not test_name:
        raise ValueError(f"invalid pytest node id: {node_id}")
    test_file = Path(file_part)
    if not test_file.exists():
        raise ValueError(f"pytest file does not exist for assertion: {node_id}")
    content = test_file.read_text(encoding="utf-8")
    if f"def {test_name}(" not in content:
        raise ValueError(f"pytest test function does not exist for assertion: {node_id}")


def _assert_fixture_exists(path: str) -> None:
    if not Path(path).exists():
        raise ValueError(f"fixture does not exist for assertion: {path}")


def _validate_assertion_references(value: Any) -> None:
    if isinstance(value, dict):
        verified_by = value.get("verified_by")
        if isinstance(verified_by, str):
            _assert_test_node_exists(verified_by)

        fixtures = value.get("fixtures")
        if isinstance(fixtures, list):
            for fixture_path in fixtures:
                if isinstance(fixture_path, str):
                    _assert_fixture_exists(fixture_path)

        for nested in value.values():
            _validate_assertion_references(nested)
        return

    if isinstance(value, list):
        for item in value:
            _validate_assertion_references(item)


def build_integration_confidence_matrix(
    *,
    jira_mapping_path: str | Path,
    servicenow_mapping_path: str | Path,
    assertions_path: str | Path,
) -> dict[str, Any]:
    jira_events = sorted(load_jira_mapping_config(str(jira_mapping_path)).routes.keys())
    servicenow_events = sorted(
        load_servicenow_mapping_config(str(servicenow_mapping_path)).routes.keys()
    )
    assertions = _load_confidence_assertions(assertions_path)

    jira_assertions = assertions["integrations"]["jira"]
    servicenow_assertions = assertions["integrations"]["servicenow"]

    _validate_assertion_references(jira_assertions)
    _validate_assertion_references(servicenow_assertions)

    matrix: dict[str, Any] = {
        "schema_version": "2",
        "generated_from": {
            "jira_mapping": str(jira_mapping_path),
            "servicenow_mapping": str(servicenow_mapping_path),
            "assertions": str(assertions_path),
        },
        "integrations": {
            "jira": {
                "supported_event_types": jira_events,
                **jira_assertions,
            },
            "servicenow": {
                "supported_event_types": servicenow_events,
                **servicenow_assertions,
            },
        },
    }
    return matrix


def render_integration_confidence_matrix_json(
    *,
    jira_mapping_path: str | Path,
    servicenow_mapping_path: str | Path,
    assertions_path: str | Path,
) -> str:
    payload = build_integration_confidence_matrix(
        jira_mapping_path=jira_mapping_path,
        servicenow_mapping_path=servicenow_mapping_path,
        assertions_path=assertions_path,
    )
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
