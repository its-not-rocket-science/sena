#!/usr/bin/env python3
"""Generate synthetic tampered audit fixtures for verifier regression tests."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from sena.audit.chain import append_audit_record, compute_chain_hash
from sena.audit.sinks import JsonlFileAuditSink, RotationPolicy


CASES = (
    "record_deletion",
    "record_reordering",
    "duplicate_decision_id",
    "sequence_gap_rotated",
    "recomputed_hash_tamper",
    "manifest_segment_divergence",
    "signature_without_verifier",
    "truncated_jsonl",
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(item, sort_keys=True) for item in rows) + "\n",
        encoding="utf-8",
    )


def _bootstrap(out_dir: Path, *, rotate: bool) -> JsonlFileAuditSink:
    sink = JsonlFileAuditSink(
        path=str(out_dir / "audit.jsonl"),
        rotation=RotationPolicy(max_file_bytes=250) if rotate else None,
    )
    for i in range(6):
        append_audit_record(
            sink,
            {
                "decision_id": f"fixture-{i}",
                "outcome": "APPROVED" if i % 2 == 0 else "BLOCKED",
            },
        )
    return sink


def generate_fixture(case: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    rotate = case in {"sequence_gap_rotated", "manifest_segment_divergence"}
    _bootstrap(out_dir, rotate=rotate)
    audit_path = out_dir / "audit.jsonl"

    if case == "record_deletion":
        rows = _read_jsonl(audit_path)
        _write_jsonl(audit_path, rows[:2] + rows[3:])
    elif case == "record_reordering":
        rows = _read_jsonl(audit_path)
        _write_jsonl(audit_path, [rows[0], rows[2], rows[1], *rows[3:]])
    elif case == "duplicate_decision_id":
        rows = _read_jsonl(audit_path)
        rows[2]["decision_id"] = str(rows[1]["decision_id"])
        rows[2]["chain_hash"] = compute_chain_hash(
            {k: v for k, v in rows[2].items() if k != "chain_hash"},
            rows[2].get("previous_chain_hash"),
        )
        _write_jsonl(audit_path, rows)
    elif case == "sequence_gap_rotated":
        manifest = json.loads((out_dir / "audit.jsonl.manifest.json").read_text())
        first_segment = out_dir / manifest["segments"][0]["file"]
        rows = _read_jsonl(first_segment)
        rows[0]["storage_sequence_number"] = 777
        rows[0]["chain_hash"] = compute_chain_hash(
            {k: v for k, v in rows[0].items() if k != "chain_hash"},
            rows[0].get("previous_chain_hash"),
        )
        _write_jsonl(first_segment, rows)
    elif case == "recomputed_hash_tamper":
        rows = _read_jsonl(audit_path)
        rows[1]["decision_id"] = "fixture-0"
        rows[1]["chain_hash"] = compute_chain_hash(
            {k: v for k, v in rows[1].items() if k != "chain_hash"},
            rows[1].get("previous_chain_hash"),
        )
        _write_jsonl(audit_path, rows)
    elif case == "manifest_segment_divergence":
        manifest_path = out_dir / "audit.jsonl.manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["segments"][0]["record_count"] += 1
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8"
        )
    elif case == "signature_without_verifier":
        rows = _read_jsonl(audit_path)
        rows[0]["signature"] = "deadbeef"
        _write_jsonl(audit_path, rows)
    elif case == "truncated_jsonl":
        with audit_path.open("a", encoding="utf-8") as handle:
            handle.write('{"decision_id":"truncated"')
    else:
        raise ValueError(f"unsupported case: {case}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, choices=CASES)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    generate_fixture(args.case, args.output_dir)
    print(
        json.dumps(
            {
                "status": "ok",
                "case": args.case,
                "output_dir": str(args.output_dir),
                "audit_path": str(args.output_dir / "audit.jsonl"),
            },
            indent=2,
        )
    )
