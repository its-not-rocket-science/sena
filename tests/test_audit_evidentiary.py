from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from sena.audit.chain import append_audit_record, verify_audit_chain
from sena.audit.evidentiary import (
    AuditRecordSigner,
    AuditRecordVerifier,
    SymmetricSigningKey,
    export_evidence_bundle,
)
from sena.audit.sqlite_sink import SQLiteAppendOnlyAuditSink


def _signer() -> AuditRecordSigner:
    return AuditRecordSigner(
        keys=(
            SymmetricSigningKey(
                key_id="audit-k1", signer_identity="auditor-a", secret="secret-a"
            ),
            SymmetricSigningKey(
                key_id="audit-k2", signer_identity="auditor-b", secret="secret-b"
            ),
        )
    )


def test_evidentiary_signatures_detect_tamper(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.jsonl"
    signer = _signer()
    verifier = AuditRecordVerifier.from_signer(signer)

    append_audit_record(str(audit_path), {"decision_id": "dec-1", "outcome": "APPROVED"}, signer=signer)
    append_audit_record(str(audit_path), {"decision_id": "dec-2", "outcome": "BLOCKED"}, signer=signer)

    ok = verify_audit_chain(str(audit_path), verifier=verifier)
    assert ok["valid"] is True

    lines = [json.loads(line) for line in audit_path.read_text().splitlines()]
    lines[1]["outcome"] = "APPROVED"
    audit_path.write_text("\n".join(json.dumps(item, sort_keys=True) for item in lines) + "\n")

    broken = verify_audit_chain(str(audit_path), verifier=verifier)
    assert broken["valid"] is False
    assert any("signature_verification_failed" in err for err in broken["errors"])


def test_export_evidence_bundle_includes_required_fields(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.jsonl"
    signer = _signer()
    append_audit_record(
        str(audit_path),
        {
            "decision_id": "dec-bundle",
            "outcome": "ESCALATE",
            "input_payload": {"action": "export_data"},
            "policy_version": "2026.04",
        },
        signer=signer,
    )

    bundle = export_evidence_bundle(str(audit_path), "dec-bundle")
    assert bundle["input_payload"] == {"action": "export_data"}
    assert bundle["policy_version"] == "2026.04"
    assert bundle["signature"]["value"]
    assert bundle["timestamp"]["rfc3339"]
    assert bundle["hash_chain_proof"]["chain_hash"]


def test_sqlite_append_only_table_blocks_update_delete(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "audit.sqlite"
    sink = SQLiteAppendOnlyAuditSink(str(sqlite_path))
    append_audit_record(sink, {"decision_id": "dec-1", "outcome": "APPROVED"})

    with sqlite3.connect(sqlite_path) as conn:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("UPDATE audit_log SET decision_id='mutated' WHERE storage_sequence_number=1")
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM audit_log WHERE storage_sequence_number=1")


def test_cli_audit_verify_evidence(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.jsonl"
    keyring_path = tmp_path / "keyring.json"
    keyring_path.write_text(
        json.dumps(
            {
                "keys": [
                    {
                        "key_id": "audit-k1",
                        "signer_identity": "auditor-a",
                        "secret": "secret-a",
                    }
                ]
            }
        )
    )
    signer = AuditRecordSigner(
        keys=(
            SymmetricSigningKey(
                key_id="audit-k1", signer_identity="auditor-a", secret="secret-a"
            ),
        )
    )
    append_audit_record(str(audit_path), {"decision_id": "dec-cli", "outcome": "APPROVED"}, signer=signer)

    env = dict(os.environ)
    env["PYTHONPATH"] = f"src:{env.get('PYTHONPATH', '')}".rstrip(":")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sena.cli.main",
            "audit",
            "--audit-path",
            str(audit_path),
            "verify-evidence",
            "--keyring",
            str(keyring_path),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["valid"] is True
