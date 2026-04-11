from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from sena.evidence_pack import stable_zip_dir
from sena.integrations.approval import DeadLetterItem
from sena.integrations.jira import (
    AllowAllJiraWebhookVerifier,
    JiraConnector,
    load_jira_mapping_config,
)
from sena.integrations.persistence import SQLiteIntegrationReliabilityStore


class _ReplayClient:
    def publish_comment(self, issue_key: str, message: str) -> dict[str, Any]:
        return {
            "status": "ok",
            "issue_key": issue_key,
            "message": message,
            "channel": "replay-client",
        }

    def publish_status(self, issue_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "ok",
            "issue_key": issue_key,
            "payload": payload,
            "channel": "replay-client",
        }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate reproducible SQLite connector reliability durability evidence"
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output-zip", type=Path)
    parser.add_argument("--clean", action="store_true")
    return parser.parse_args()


def _connector(db_path: Path) -> JiraConnector:
    return JiraConnector(
        config=load_jira_mapping_config("src/sena/examples/integrations/jira_mappings.yaml"),
        verifier=AllowAllJiraWebhookVerifier(),
        reliability_db_path=str(db_path),
        delivery_client=_ReplayClient(),
    )


def main() -> None:
    args = parse_args()
    if args.clean and args.output_dir.exists():
        shutil.rmtree(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    artifacts_dir = args.output_dir / "artifacts"
    db_path = artifacts_dir / "integration_reliability.db"

    store = SQLiteIntegrationReliabilityStore(str(db_path))

    with sqlite3.connect(str(db_path)) as conn:
        created_tables = sorted(
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if str(row[0]).startswith("delivery_") or str(row[0]).startswith("outbound_")
        )

    first_seen = store.mark_if_new("delivery-restart-proof-1")
    second_seen = store.mark_if_new("delivery-restart-proof-1")
    restart_store = SQLiteIntegrationReliabilityStore(str(db_path))
    duplicate_summary = restart_store.duplicate_suppression_summary()

    store.mark_completed(
        "operation-complete-1",
        target="comment",
        payload={"issue_key": "RISK-101"},
        result={"status": "ok", "message": "completed"},
        attempts=1,
        max_attempts=3,
    )
    completion_after_restart = restart_store.get_completion("operation-complete-1")

    store.push(
        DeadLetterItem(
            operation_key="operation-dlq-1",
            target="comment",
            error="timeout",
            attempts=3,
            max_attempts=3,
            first_failed_at="2026-04-11T00:00:00+00:00",
            last_failed_at="2026-04-11T00:00:05+00:00",
            payload={"issue_key": "RISK-201", "message": "retry me"},
        )
    )
    dlq_after_restart = restart_store.list_dead_letter_records(limit=10)

    connector_after_restart = _connector(db_path)
    replay_result = connector_after_restart.replay_dead_letter(dlq_after_restart[0].id)

    restart_store.push(
        DeadLetterItem(
            operation_key="operation-dlq-2",
            target="comment",
            error="rate-limit",
            attempts=2,
            max_attempts=3,
            first_failed_at="2026-04-11T00:01:00+00:00",
            last_failed_at="2026-04-11T00:01:05+00:00",
            payload={"issue_key": "RISK-202", "message": "manual remediation"},
        )
    )
    connector_second_restart = _connector(db_path)
    dlq_second = connector_second_restart.outbound_dead_letter_records(limit=10)
    manual_redrive_result = connector_second_restart.manual_redrive_dead_letter(
        int(dlq_second[0]["id"]), note="operator-redrive"
    )

    backup_db = artifacts_dir / "integration_reliability.backup.db"
    restored_db = artifacts_dir / "integration_reliability.restored.db"
    with sqlite3.connect(str(db_path)) as source_conn, sqlite3.connect(str(backup_db)) as backup_conn:
        source_conn.backup(backup_conn)
    with sqlite3.connect(str(backup_db)) as backup_conn, sqlite3.connect(str(restored_db)) as restored_conn:
        backup_conn.backup(restored_conn)
    with sqlite3.connect(str(restored_db)) as conn:
        integrity_check = str(conn.execute("PRAGMA integrity_check").fetchone()[0])

    restored_store = SQLiteIntegrationReliabilityStore(str(restored_db))
    restored_summary = restored_store.reliability_summary()

    checks = {
        "connector_reliability_db_created": db_path.exists() and len(created_tables) >= 5,
        "inbound_duplicate_suppression_persists_after_restart": (
            first_seen is True
            and second_seen is False
            and duplicate_summary["inbound"]["suppressed_total"] == 1
        ),
        "outbound_completion_persists_after_restart": completion_after_restart is not None,
        "dead_letter_persists_after_restart": len(dlq_after_restart) == 1,
        "replay_after_restart": replay_result["status"] == "replayed",
        "manual_redrive_after_restart": manual_redrive_result["status"] == "manually_redriven",
        "backup_restore_validated": (
            integrity_check == "ok"
            and restored_summary["completion_total"] >= 2
            and restored_summary["dead_letter_volume"] == 0
        ),
    }

    evidence = {
        "checks": checks,
        "created_tables": created_tables,
        "duplicate_summary": duplicate_summary,
        "completion_after_restart": (
            completion_after_restart.__dict__ if completion_after_restart else None
        ),
        "dead_letter_before_replay": [item.__dict__ for item in dlq_after_restart],
        "replay_result": replay_result,
        "manual_redrive_result": manual_redrive_result,
        "restored_summary": restored_summary,
        "integrity_check": integrity_check,
        "paths": {
            "db": str(db_path),
            "backup_db": str(backup_db),
            "restored_db": str(restored_db),
        },
    }

    _write_json(artifacts_dir / "sqlite_reliability_evidence.json", evidence)
    _write_json(
        artifacts_dir / "sqlite_reliability_claims.json",
        {
            "claim_to_check": [
                {
                    "claim": "connector reliability DB creation",
                    "check": "connector_reliability_db_created",
                },
                {
                    "claim": "inbound duplicate suppression persistence across restart",
                    "check": "inbound_duplicate_suppression_persists_after_restart",
                },
                {
                    "claim": "outbound completion persistence across restart",
                    "check": "outbound_completion_persists_after_restart",
                },
                {
                    "claim": "dead-letter persistence across restart",
                    "check": "dead_letter_persists_after_restart",
                },
                {
                    "claim": "replay/manual-redrive after restart",
                    "check": "replay_after_restart + manual_redrive_after_restart",
                },
                {
                    "claim": "backup and restore validation",
                    "check": "backup_restore_validated",
                },
            ]
        },
    )

    summary_lines = [
        "# SQLite Reliability Durability Evidence",
        "",
        "Evidence run outputs:",
        "- sqlite_reliability_evidence.json",
        "- sqlite_reliability_claims.json",
        "- integration_reliability.db",
        "- integration_reliability.backup.db",
        "- integration_reliability.restored.db",
        "",
        "Check results:",
    ]
    summary_lines.extend(
        [f"- {'PASS' if ok else 'FAIL'}: {name}" for name, ok in checks.items()]
    )
    (args.output_dir / "SUMMARY.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    result = {
        "status": "ok" if all(checks.values()) else "failed",
        "output_dir": str(args.output_dir),
        "checks": checks,
    }
    if args.output_zip:
        stable_zip_dir(args.output_dir, args.output_zip)
        result["output_zip"] = str(args.output_zip)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
