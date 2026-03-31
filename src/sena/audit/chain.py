from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_chain_hash(record: dict[str, Any], previous_chain_hash: str | None) -> str:
    material = {
        "previous_chain_hash": previous_chain_hash,
        "record": record,
    }
    return hashlib.sha256(_canonical_json(material).encode("utf-8")).hexdigest()


def append_audit_record(path: str, record: dict[str, Any]) -> dict[str, Any]:
    sink = Path(path)
    sink.parent.mkdir(parents=True, exist_ok=True)

    previous_chain_hash = None
    if sink.exists():
        with sink.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                previous_chain_hash = json.loads(line)["chain_hash"]

    chain_hash = compute_chain_hash(record, previous_chain_hash)
    payload = {
        **record,
        "previous_chain_hash": previous_chain_hash,
        "chain_hash": chain_hash,
    }
    with sink.open("a", encoding="utf-8") as handle:
        handle.write(_canonical_json(payload) + "\n")
    return payload


def verify_audit_chain(path: str) -> dict[str, Any]:
    sink = Path(path)
    if not sink.exists():
        return {"valid": False, "error": f"audit file not found: {path}", "records": 0}

    previous_chain_hash = None
    count = 0
    with sink.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            count += 1
            row = json.loads(line)
            claimed_previous = row.get("previous_chain_hash")
            if claimed_previous != previous_chain_hash:
                return {
                    "valid": False,
                    "error": f"line {line_number}: previous_chain_hash mismatch",
                    "records": count,
                }
            current_hash = row.get("chain_hash")
            record = {
                k: v
                for k, v in row.items()
                if k not in {"chain_hash", "previous_chain_hash"}
            }
            expected_hash = compute_chain_hash(record, previous_chain_hash)
            if expected_hash != current_hash:
                return {
                    "valid": False,
                    "error": f"line {line_number}: chain_hash mismatch",
                    "records": count,
                }
            previous_chain_hash = current_hash

    return {"valid": True, "records": count, "head": previous_chain_hash}
