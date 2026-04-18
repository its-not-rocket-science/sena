from __future__ import annotations

import json
import os
import subprocess
import sys

from sena.integrations.approval import DeadLetterItem
from sena.integrations.jira import (
    AllowAllJiraWebhookVerifier,
    JiraConnector,
    load_jira_mapping_config,
)
from sena.integrations.persistence import SQLiteIntegrationReliabilityStore


class _ReplayClient:
    def publish_comment(self, issue_key: str, message: str) -> dict[str, str]:
        return {"status": "ok", "issue_key": issue_key, "message": message}

    def publish_status(self, issue_key: str, payload: dict) -> dict:
        return {"status": "ok", "issue_key": issue_key, "payload": payload}


def _connector(db_path: str) -> JiraConnector:
    return JiraConnector(
        config=load_jira_mapping_config("src/sena/examples/integrations/jira_mappings.yaml"),
        verifier=AllowAllJiraWebhookVerifier(),
        reliability_db_path=db_path,
        delivery_client=_ReplayClient(),
    )


def test_sqlite_reliability_persists_inbound_completion_and_dead_letter_across_restart(tmp_path) -> None:
    db_path = tmp_path / "reliability.db"
    first = SQLiteIntegrationReliabilityStore(str(db_path))

    assert first.mark_if_new("delivery-1") == "new"
    assert first.mark_if_new("delivery-1") == "duplicate"

    first.mark_completed(
        "operation-1",
        target="comment",
        payload={"issue_key": "RISK-1"},
        result={"status": "ok"},
        attempts=1,
        max_attempts=2,
    )
    first.push(
        DeadLetterItem(
            operation_key="operation-2",
            target="comment",
            error="timeout",
            attempts=2,
            max_attempts=2,
            first_failed_at="2026-04-11T00:00:00+00:00",
            last_failed_at="2026-04-11T00:00:01+00:00",
            payload={"issue_key": "RISK-2", "message": "retry"},
        )
    )

    second = SQLiteIntegrationReliabilityStore(str(db_path))
    assert second.duplicate_suppression_summary()["inbound"]["suppressed_total"] == 1
    assert second.get_completion("operation-1") is not None
    assert len(second.list_dead_letter_records(limit=10)) == 1


def test_replay_and_manual_redrive_work_after_restart(tmp_path) -> None:
    db_path = tmp_path / "reliability.db"
    store = SQLiteIntegrationReliabilityStore(str(db_path))
    store.push(
        DeadLetterItem(
            operation_key="operation-replay",
            target="comment",
            error="timeout",
            attempts=2,
            max_attempts=2,
            first_failed_at="2026-04-11T00:00:00+00:00",
            last_failed_at="2026-04-11T00:00:01+00:00",
            payload={"issue_key": "RISK-3", "message": "replay"},
        )
    )

    connector = _connector(str(db_path))
    dead_letter_id = connector.outbound_dead_letter_records(limit=10)[0]["id"]
    replay_result = connector.replay_dead_letter(int(dead_letter_id))
    assert replay_result["status"] == "replayed"

    restart_store = SQLiteIntegrationReliabilityStore(str(db_path))
    restart_store.push(
        DeadLetterItem(
            operation_key="operation-manual",
            target="comment",
            error="timeout",
            attempts=2,
            max_attempts=2,
            first_failed_at="2026-04-11T00:01:00+00:00",
            last_failed_at="2026-04-11T00:01:01+00:00",
            payload={"issue_key": "RISK-4", "message": "manual"},
        )
    )
    connector_after_restart = _connector(str(db_path))
    manual_id = connector_after_restart.outbound_dead_letter_records(limit=10)[0]["id"]
    manual_result = connector_after_restart.manual_redrive_dead_letter(
        int(manual_id), note="manual"
    )
    assert manual_result["status"] == "manually_redriven"

    assert restart_store.reliability_summary()["completion_total"] == 2
    assert restart_store.reliability_summary()["dead_letter_volume"] == 0


def test_sqlite_reliability_evidence_script_generates_compact_bundle(tmp_path) -> None:
    out_dir = tmp_path / "evidence"
    out_zip = tmp_path / "evidence.zip"

    run = subprocess.run(
        [
            sys.executable,
            "scripts/generate_sqlite_reliability_evidence.py",
            "--output-dir",
            str(out_dir),
            "--output-zip",
            str(out_zip),
            "--clean",
        ],
        check=True,
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": "src"},
    )

    payload = json.loads(run.stdout)
    assert payload["status"] == "ok"
    assert out_zip.exists()
    evidence = json.loads((out_dir / "artifacts" / "sqlite_reliability_evidence.json").read_text())
    assert all(evidence["checks"].values())
