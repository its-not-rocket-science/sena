from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

AuditEntry = dict[str, Any]


@dataclass(frozen=True)
class MerkleTree:
    """Binary Merkle tree represented as bottom-up hash levels."""

    levels: list[list[str]]

    @property
    def root(self) -> str:
        if not self.levels or not self.levels[-1]:
            return ""
        return self.levels[-1][0]


def _canonical_json(entry: AuditEntry) -> str:
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_hex(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _combine_hashes(left: str, right: str) -> str:
    # Canonical ordering makes proof verification independent of sibling direction.
    lo, hi = sorted((left, right))
    return _sha256_hex(f"{lo}{hi}")


def build_merkle_tree(entries: list[AuditEntry]) -> MerkleTree:
    if not entries:
        raise ValueError("cannot build Merkle tree from zero entries")

    leaves = [_sha256_hex(_canonical_json(entry)) for entry in entries]
    levels: list[list[str]] = [leaves]
    current = leaves
    while len(current) > 1:
        next_level: list[str] = []
        for i in range(0, len(current), 2):
            left = current[i]
            right = current[i + 1] if i + 1 < len(current) else current[i]
            next_level.append(_combine_hashes(left, right))
        levels.append(next_level)
        current = next_level
    return MerkleTree(levels=levels)


def get_proof(tree: MerkleTree, entry_index: int) -> list[str]:
    if not tree.levels or not tree.levels[0]:
        raise ValueError("Merkle tree has no leaves")
    if entry_index < 0 or entry_index >= len(tree.levels[0]):
        raise IndexError("entry_index out of range")

    proof: list[str] = []
    index = entry_index
    for level in tree.levels[:-1]:
        sibling_index = index + 1 if index % 2 == 0 else index - 1
        if sibling_index >= len(level):
            sibling_index = index
        proof.append(level[sibling_index])
        index //= 2
    return proof


def verify_proof(entry: AuditEntry, proof: list[str], expected_root: str) -> bool:
    current_hash = _sha256_hex(_canonical_json(entry))
    for sibling_hash in proof:
        current_hash = _combine_hashes(current_hash, sibling_hash)
    return current_hash == expected_root
