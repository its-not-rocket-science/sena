from __future__ import annotations

from pathlib import Path

from sena.integrations.confidence_matrix import render_integration_confidence_matrix_json


JIRA_MAPPING = "src/sena/examples/integrations/jira_mappings.yaml"
SERVICENOW_MAPPING = "src/sena/examples/integrations/servicenow_mappings.yaml"
MATRIX_FIXTURE = Path("tests/fixtures/integrations/confidence_matrix.json")


def test_integration_confidence_matrix_fixture_is_current() -> None:
    rendered = render_integration_confidence_matrix_json(
        jira_mapping_path=JIRA_MAPPING,
        servicenow_mapping_path=SERVICENOW_MAPPING,
    )
    assert rendered == MATRIX_FIXTURE.read_text(encoding="utf-8")
