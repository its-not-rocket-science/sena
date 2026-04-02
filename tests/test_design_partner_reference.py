from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sena.integrations.servicenow import (
    ServiceNowConnector,
    ServiceNowIntegrationError,
    load_servicenow_mapping_config,
)


def test_design_partner_reference_runs_end_to_end(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    source = repo_root / "examples" / "design_partner_reference"
    target = tmp_path / "design_partner_reference"
    shutil.copytree(source, target)

    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root / "src")
    subprocess.run(
        [sys.executable, str(target / "run_reference.py")], check=True, env=env
    )

    manifest = json.loads((target / "artifacts" / "release-manifest.json").read_text())
    assert manifest["signer"]["signature"]

    simulation = json.loads(
        (target / "artifacts" / "simulation-report.json").read_text()
    )
    assert simulation["changed_scenarios"] >= 1
    emergency_change = next(
        change
        for change in simulation["changes"]
        if change["scenario_id"] == "emergency_privileged_no_chain"
    )
    assert emergency_change["before_outcome"] == "ESCALATE_FOR_HUMAN_REVIEW"
    assert emergency_change["after_outcome"] == "BLOCKED"

    promotion = json.loads(
        (target / "artifacts" / "promotion-validation.json").read_text()
    )
    assert promotion["promotion_validation"]["valid"] is True
    assert promotion["signature_verification"]["valid"] is True

    evaluations = json.loads(
        (target / "artifacts" / "evaluation-results.json").read_text()
    )
    assert len(evaluations) == 3

    audit = json.loads(
        (target / "artifacts" / "audit-chain-verification.json").read_text()
    )
    assert audit["valid"] is True

    replay_stable = json.loads(
        (target / "artifacts" / "replay-report-stable.json").read_text()
    )
    assert replay_stable["changed_outcomes"] == 0
    assert replay_stable["changed_matched_controls"] == 0

    replay_update = json.loads(
        (target / "artifacts" / "replay-report-policy-update.json").read_text()
    )
    assert replay_update["changed_outcomes"] >= 1

    portability_examples = json.loads(
        (target / "artifacts" / "normalized-event-examples.json").read_text()
    )
    assert {example["source_system"] for example in portability_examples} == {
        "servicenow",
        "jira",
    }

    review_dir = target / "artifacts" / "review_packages"
    assert len(list(review_dir.glob("*.json"))) == 3


@pytest.mark.parametrize(
    "fixture_name,expected_error",
    [
        ("servicenow_missing_event_type.json", "missing event_type"),
        (
            "servicenow_missing_required_fields.json",
            "missing required fields",
        ),
    ],
)
def test_design_partner_reference_malformed_servicenow_payloads_are_rejected(
    fixture_name: str,
    expected_error: str,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    fixture = repo_root / "examples" / "design_partner_reference" / "fixtures" / "malformed" / fixture_name
    envelope = json.loads(fixture.read_text(encoding="utf-8"))
    envelope["raw_body"] = b""

    connector = ServiceNowConnector(
        config=load_servicenow_mapping_config(
            str(
                repo_root
                / "examples"
                / "design_partner_reference"
                / "integration"
                / "servicenow_mapping.yaml"
            )
        )
    )
    with pytest.raises(ServiceNowIntegrationError, match=expected_error):
        connector.handle_event(envelope)
