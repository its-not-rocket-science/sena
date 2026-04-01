from __future__ import annotations

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from sena.audit.chain import compute_chain_hash  # noqa: E402
from sena.core.enums import RuleDecision, Severity  # noqa: E402
from sena.core.models import PolicyRule  # noqa: E402
from sena.policy.lifecycle import diff_rule_sets  # noqa: E402
from sena.policy.parser import PolicyParseError, parse_policy_file  # noqa: E402


@settings(max_examples=80)
@given(st.lists(st.text(min_size=1, max_size=8), min_size=1, max_size=8))
def test_lifecycle_diff_invariants(ids: list[str]) -> None:
    unique = list(dict.fromkeys(ids))
    rules = [
        PolicyRule(
            id=rule_id,
            description="r",
            severity=Severity.LOW,
            inviolable=False,
            applies_to=["act"],
            condition={"field": "v", "eq": rule_id},
            decision=RuleDecision.ALLOW,
            reason="r",
        )
        for rule_id in unique
    ]

    diff = diff_rule_sets(rules, rules)
    assert diff.added_rule_ids == []
    assert diff.removed_rule_ids == []
    assert diff.changed_rule_ids == []


@settings(max_examples=60)
@given(record=st.dictionaries(st.text(min_size=1, max_size=6), st.one_of(st.integers(), st.text(max_size=8)), max_size=5))
def test_audit_chain_hash_is_stable(record: dict[str, object]) -> None:
    first = compute_chain_hash(record, "prev")
    second = compute_chain_hash(record, "prev")
    assert first == second


@settings(max_examples=50)
@given(raw=st.text(min_size=1, max_size=80))
def test_parser_stability_for_malformed_payloads(raw: str, tmp_path) -> None:
    policy_file = tmp_path / "fuzz.yaml"
    policy_file.write_text(raw, encoding="utf-8")

    try:
        parse_policy_file(policy_file)
    except (PolicyParseError, UnicodeDecodeError, ValueError, TypeError):
        assert True
