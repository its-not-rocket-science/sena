from __future__ import annotations

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from sena.core.models import ActionProposal  # noqa: E402
from sena.engine.evaluator import PolicyEvaluator  # noqa: E402
from sena.policy.parser import load_policy_bundle  # noqa: E402


def _json_scalar_strategy() -> st.SearchStrategy[None | bool | int | float | str]:
    return st.one_of(
        st.none(),
        st.booleans(),
        st.integers(),
        st.floats(allow_nan=False, allow_infinity=False),
        st.text(max_size=40),
    )


def _json_value_strategy() -> st.SearchStrategy[object]:
    return st.recursive(
        _json_scalar_strategy(),
        lambda children: st.one_of(
            st.lists(children, max_size=5),
            st.dictionaries(st.text(min_size=1, max_size=20), children, max_size=5),
        ),
        max_leaves=20,
    )


def _proposal_strategy() -> st.SearchStrategy[ActionProposal]:
    return st.builds(
        ActionProposal,
        action_type=st.text(min_size=1, max_size=40),
        request_id=st.one_of(st.none(), st.text(min_size=1, max_size=40)),
        actor_id=st.one_of(st.none(), st.text(min_size=1, max_size=40)),
        actor_role=st.one_of(st.none(), st.text(min_size=1, max_size=40)),
        attributes=st.dictionaries(
            st.text(min_size=1, max_size=20),
            _json_value_strategy(),
            max_size=8,
        ),
    )


@settings(max_examples=200)
@given(proposal=_proposal_strategy(), facts=st.dictionaries(st.text(min_size=1, max_size=20), _json_value_strategy(), max_size=8))
def test_evaluator_is_deterministic_for_same_inputs(proposal: ActionProposal, facts: dict[str, object]) -> None:
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    evaluator = PolicyEvaluator(rules, policy_bundle=metadata)

    first = evaluator.evaluate(proposal, facts)
    second = evaluator.evaluate(proposal, facts)

    assert first.outcome == second.outcome
    assert first.decision_hash == second.decision_hash
    assert first.audit_record is not None and second.audit_record is not None
    assert first.audit_record.input_fingerprint == second.audit_record.input_fingerprint
    assert first.matched_rules == second.matched_rules
    assert first.evaluated_rules == second.evaluated_rules
    assert first.missing_fields == second.missing_fields
    assert first.conflicting_rules == second.conflicting_rules


@settings(max_examples=300)
@given(proposal=_proposal_strategy(), facts=st.dictionaries(st.text(min_size=1, max_size=20), _json_value_strategy(), max_size=8))
def test_evaluator_does_not_crash_on_random_json_like_inputs(
    proposal: ActionProposal, facts: dict[str, object]
) -> None:
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    evaluator = PolicyEvaluator(rules, policy_bundle=metadata)

    trace = evaluator.evaluate(proposal, facts)

    assert trace.decision_hash
    assert trace.outcome is not None
    assert trace.audit_record is not None
