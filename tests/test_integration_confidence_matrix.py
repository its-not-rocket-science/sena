from __future__ import annotations

from pathlib import Path

from sena.integrations.confidence_matrix import render_integration_confidence_matrix_json


JIRA_MAPPING = "src/sena/examples/integrations/jira_mappings.yaml"
SERVICENOW_MAPPING = "src/sena/examples/integrations/servicenow_mappings.yaml"
ASSERTIONS = "tests/fixtures/integrations/confidence_assertions.json"
PUBLISHED_MATRIX = Path("docs/artifacts/integrations/jira_servicenow_confidence_matrix.json")


def test_integration_confidence_matrix_published_artifact_is_current() -> None:
    rendered = render_integration_confidence_matrix_json(
        jira_mapping_path=JIRA_MAPPING,
        servicenow_mapping_path=SERVICENOW_MAPPING,
        assertions_path=ASSERTIONS,
    )
    assert rendered == PUBLISHED_MATRIX.read_text(encoding="utf-8")
