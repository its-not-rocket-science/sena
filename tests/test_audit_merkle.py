from sena.audit.merkle import build_merkle_tree, get_proof, verify_proof


def test_merkle_tree_proof_roundtrip() -> None:
    entries = [
        {"decision_id": "d1", "outcome": "APPROVED"},
        {"decision_id": "d2", "outcome": "BLOCKED"},
        {"decision_id": "d3", "outcome": "ESCALATE_FOR_HUMAN_REVIEW"},
    ]
    tree = build_merkle_tree(entries)

    proof = get_proof(tree, 1)

    assert verify_proof(entries[1], proof, tree.root) is True
    assert verify_proof(entries[0], proof, tree.root) is False


def test_merkle_tree_rejects_empty_entries() -> None:
    try:
        build_merkle_tree([])
    except ValueError as exc:
        assert "zero entries" in str(exc)
    else:
        raise AssertionError("expected ValueError for empty Merkle tree")
