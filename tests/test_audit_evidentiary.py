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
from sena.audit.compliance import (
    build_control_mapping,
    build_evidence_vault,
    export_control_audit_package,
)
from sena.audit.sqlite_sink import SQLiteAppendOnlyAuditSink
from sena.policy.parser import load_policy_bundle


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
            "canonical_replay_payload": {"decision_hash": "abc123"},
            "operational_metadata": {"decision_timestamp": "2026-04-10T00:00:00Z"},
        },
        signer=signer,
    )

    bundle = export_evidence_bundle(str(audit_path), "dec-bundle")
    assert bundle["input_payload"] == {"action": "export_data"}
    assert bundle["policy_version"] == "2026.04"
    assert bundle["signature"]["value"]
    assert bundle["timestamp"]["rfc3339"]
    assert bundle["hash_chain_proof"]["chain_hash"]
    assert bundle["determinism_contract"]["scope"] == "canonical_replay_payload_only"
    assert bundle["determinism_contract"]["canonical_replay_payload"]["decision_hash"] == "abc123"


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


def test_control_mapping_vault_and_audit_package(tmp_path: Path) -> None:
    policy_dir = tmp_path / "policy"
    policy_dir.mkdir()
    (policy_dir / "rules.yaml").write_text(
        """
- id: block_high_risk
  description: Block high-risk requests
  severity: high
  inviolable: true
  applies_to: [approve_change_request]
  condition:
    field: risk_score
    gte: 90
  decision: BLOCK
  reason: High risk must be blocked
  control_ids: [SOC2:CC7.2, ISO27001:A.8.16]
- id: allow_low_risk
  description: Allow low-risk requests
  severity: low
  inviolable: false
  applies_to: [approve_change_request]
  condition:
    field: risk_score
    lt: 20
  decision: ALLOW
  reason: Low risk can pass
  control_ids: [SOC2:CC7.2]
""".strip()
    )

    rules, _ = load_policy_bundle(policy_dir)
    control_mapping = build_control_mapping(rules)
    assert len(control_mapping["controls"]) == 2

    audit_path = tmp_path / "audit.jsonl"
    signer = _signer()
    append_audit_record(
        str(audit_path),
        {
            "decision_id": "dec-control-1",
            "outcome": "BLOCKED",
            "matched_rule_ids": ["block_high_risk"],
            "input_payload": {"risk_score": 95},
            "policy_version": "2026.04",
        },
        signer=signer,
    )
    append_audit_record(
        str(audit_path),
        {
            "decision_id": "dec-control-2",
            "outcome": "APPROVED",
            "matched_rule_ids": ["allow_low_risk"],
            "input_payload": {"risk_score": 10},
            "policy_version": "2026.04",
        },
        signer=signer,
    )

    vault = build_evidence_vault(str(audit_path), rules)
    soc2 = next(item for item in vault["controls"] if item["control_id"] == "SOC2:CC7.2")
    assert soc2["decision_count"] == 2

    package = export_control_audit_package(str(audit_path), rules, "SOC2:CC7.2")
    assert package["control"]["control_id"] == "SOC2:CC7.2"
    assert len(package["evidence_bundles"]) == 2


def test_cli_export_control_mapping_vault_and_package(tmp_path: Path) -> None:
    policy_dir = tmp_path / "policy"
    policy_dir.mkdir()
    (policy_dir / "rules.yaml").write_text(
        """
- id: block_high_risk
  description: Block high-risk requests
  severity: high
  inviolable: true
  applies_to: [approve_change_request]
  condition:
    field: risk_score
    gte: 90
  decision: BLOCK
  reason: High risk must be blocked
  control_ids: [SOC2:CC7.2]
""".strip()
    )
    audit_path = tmp_path / "audit.jsonl"
    append_audit_record(
        str(audit_path),
        {
            "decision_id": "dec-cli-control",
            "outcome": "BLOCKED",
            "matched_rule_ids": ["block_high_risk"],
            "input_payload": {"risk_score": 95},
            "policy_version": "2026.04",
        },
        signer=_signer(),
    )

    control_map_path = tmp_path / "control-mapping.json"
    env = dict(os.environ)
    env["PYTHONPATH"] = f"src:{env.get('PYTHONPATH', '')}".rstrip(":")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "sena.cli.main",
            "audit",
            "--audit-path",
            str(audit_path),
            "export-control-mapping",
            "--policy-dir",
            str(policy_dir),
            "--output",
            str(control_map_path),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    assert control_map_path.exists()

    evidence_vault_path = tmp_path / "evidence-vault.json"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "sena.cli.main",
            "audit",
            "--audit-path",
            str(audit_path),
            "export-evidence-vault",
            "--policy-dir",
            str(policy_dir),
            "--output",
            str(evidence_vault_path),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    assert evidence_vault_path.exists()

    control_package_path = tmp_path / "control-package.json"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "sena.cli.main",
            "audit",
            "--audit-path",
            str(audit_path),
            "export-control-package",
            "--policy-dir",
            str(policy_dir),
            "--control-id",
            "SOC2:CC7.2",
            "--output",
            str(control_package_path),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    payload = json.loads(control_package_path.read_text())
    assert payload["control"]["control_id"] == "SOC2:CC7.2"
