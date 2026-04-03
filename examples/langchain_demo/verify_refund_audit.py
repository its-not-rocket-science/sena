"""Verify Merkle proof integrity for SENA decisions recorded in audit jsonl."""

from __future__ import annotations

import json
from pathlib import Path

from sena.audit.merkle import build_merkle_tree, get_proof, verify_proof


def verify_refund_audit(audit_path: str) -> dict[str, object]:
    rows = [
        json.loads(line)
        for line in Path(audit_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows:
        raise RuntimeError("No audit rows found")

    tree = build_merkle_tree(rows)
    results: list[dict[str, object]] = []
    for index, row in enumerate(rows):
        proof = get_proof(tree, index)
        results.append(
            {
                "decision_id": row.get("decision_id"),
                "proof": proof,
                "valid": verify_proof(row, proof, tree.root),
            }
        )

    return {
        "root": tree.root,
        "total_decisions": len(rows),
        "all_valid": all(item["valid"] for item in results),
        "proofs": results,
    }


if __name__ == "__main__":
    report = verify_refund_audit("./artifacts/audit/audit.jsonl")
    print(json.dumps(report, indent=2))
