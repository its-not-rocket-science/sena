from __future__ import annotations

import json
from pathlib import Path
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from sena.core.enums import DecisionOutcome, RuleDecision, Severity  # noqa: E402
from sena.core.models import (  # noqa: E402
    ActionProposal,
    ExceptionScope,
    EvaluatorConfig,
    PolicyException,
    PolicyInvariant,
    PolicyRule,
)
from sena.engine.evaluator import PolicyEvaluator  # noqa: E402
from sena.policy.interpreter import evaluate_condition_with_trace  # noqa: E402
from sena.policy.parser import PolicyParseError, parse_policy_file  # noqa: E402


SAFE_HYPOTHESIS_SETTINGS = settings(max_examples=120, derandomize=True, deadline=None)


def _valid_rule_payload(condition: dict[str, object]) -> dict[str, object]:
    return {
        "id": "r1",
        "description": "determinism",
        "severity": "low",
        "inviolable": False,
        "applies_to": ["approve_vendor_payment"],
        "condition": condition,
        "decision": "ALLOW",
        "reason": "ok",
    }


@SAFE_HYPOTHESIS_SETTINGS
@given(
    field=st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")),
        min_size=1,
        max_size=20,
    ),
    value=st.one_of(st.integers(), st.text(max_size=20), st.booleans(), st.none()),
)
def test_policy_parser_same_input_yields_same_canonical_outcome(
    field: str, value: int | str | bool | None
) -> None:
    with TemporaryDirectory() as temp_dir:
        policy_file = Path(temp_dir) / "rules.yaml"
        policy_file.write_text(
            json.dumps([_valid_rule_payload({"field": field, "eq": value})])
        )

        first = parse_policy_file(policy_file)
        second = parse_policy_file(policy_file)

    assert [asdict(rule) for rule in first] == [asdict(rule) for rule in second]


@SAFE_HYPOTHESIS_SETTINGS
@given(
    field_path=st.lists(
        st.text(
            alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")),
            min_size=1,
            max_size=12,
        ),
        min_size=1,
        max_size=4,
    ).map(".".join),
    context=st.dictionaries(
        st.text(min_size=1, max_size=10),
        st.one_of(st.integers(), st.text(max_size=20), st.booleans(), st.none()),
        max_size=8,
    ),
)
def test_interpreter_missing_fields_never_crash(
    field_path: str, context: dict[str, int | str | bool | None]
) -> None:
    result = evaluate_condition_with_trace(
        {"field": field_path, "eq": "value-that-is-often-missing"},
        context,
    )

    assert isinstance(result.matched, bool)
    assert result.missing_fields.issubset({field_path})


@SAFE_HYPOTHESIS_SETTINGS
@given(
    unknown_operator=st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")),
        min_size=3,
        max_size=16,
    ).filter(lambda name: name not in {"field", "eq", "and", "or", "not"}),
)
def test_unsupported_conditions_fail_safely_in_parser_and_interpreter(
    unknown_operator: str,
) -> None:
    with TemporaryDirectory() as temp_dir:
        policy_file = Path(temp_dir) / "invalid_rules.yaml"

        policy_file.write_text(
            json.dumps([_valid_rule_payload({"field": "amount", unknown_operator: 10})])
        )

        with pytest.raises(PolicyParseError):
            parse_policy_file(policy_file)

    interpreter_result = evaluate_condition_with_trace(
        {"field": "amount", unknown_operator: 10},
        {"amount": 100},
    )
    assert interpreter_result.matched is False


@SAFE_HYPOTHESIS_SETTINGS
@given(order=st.permutations((0, 1, 2)))
def test_precedence_is_invariant_under_rule_permutations(
    order: tuple[int, int, int],
) -> None:
    rules = [
        PolicyRule(
            id="allow_low_risk",
            description="allow low risk",
            severity=Severity.LOW,
            inviolable=False,
            applies_to=["approve_vendor_payment"],
            condition={"field": "amount", "lte": 500},
            decision=RuleDecision.ALLOW,
            reason="small payment",
        ),
        PolicyRule(
            id="escalate_large_payment",
            description="escalate larger payments",
            severity=Severity.MEDIUM,
            inviolable=False,
            applies_to=["approve_vendor_payment"],
            condition={"field": "amount", "gte": 500},
            decision=RuleDecision.ESCALATE,
            reason="review needed",
        ),
        PolicyRule(
            id="block_sanctioned_vendor",
            description="block sanctioned vendor",
            severity=Severity.HIGH,
            inviolable=False,
            applies_to=["approve_vendor_payment"],
            condition={"field": "vendor_sanctioned", "eq": True},
            decision=RuleDecision.BLOCK,
            reason="sanctioned vendor",
        ),
    ]
    proposal = ActionProposal(
        action_type="approve_vendor_payment",
        attributes={"amount": 500, "vendor_sanctioned": False},
    )
    facts = {}

    canonical_evaluator = PolicyEvaluator(
        rules,
        config=EvaluatorConfig(deterministic_mode=True),
    )
    canonical = canonical_evaluator.evaluate(proposal, facts)

    permuted_rules = [rules[index] for index in order]
    permuted_evaluator = PolicyEvaluator(
        permuted_rules,
        config=EvaluatorConfig(deterministic_mode=True),
    )
    permuted = permuted_evaluator.evaluate(proposal, facts)

    assert permuted.outcome == canonical.outcome
    assert permuted.baseline_outcome == canonical.baseline_outcome
    assert permuted.decision_hash == canonical.decision_hash
    assert sorted(rule.rule_id for rule in permuted.matched_rules) == sorted(
        rule.rule_id for rule in canonical.matched_rules
    )


@SAFE_HYPOTHESIS_SETTINGS
@given(
    exception_count=st.integers(min_value=1, max_value=4),
    approved_flags=st.lists(st.booleans(), min_size=1, max_size=4),
    expiry_offsets=st.lists(
        st.integers(min_value=-2, max_value=2), min_size=1, max_size=4
    ),
)
def test_exception_overlays_never_override_invariant_blocks(
    exception_count: int,
    approved_flags: list[bool],
    expiry_offsets: list[int],
) -> None:
    now = datetime.now(timezone.utc)
    invariant = PolicyInvariant(
        id="inv_prod_freeze",
        description="production freeze",
        applies_to=["approve_vendor_payment"],
        condition={"field": "impact_scope", "eq": "production"},
        reason="production freeze window",
    )
    allow_rule = PolicyRule(
        id="allow_if_vendor_verified",
        description="allow verified vendors",
        severity=Severity.LOW,
        inviolable=False,
        applies_to=["approve_vendor_payment"],
        condition={"field": "vendor_verified", "eq": True},
        decision=RuleDecision.ALLOW,
        reason="vendor is verified",
    )

    exceptions: list[PolicyException] = []
    for index in range(exception_count):
        approved = approved_flags[index % len(approved_flags)]
        expiry_offset = expiry_offsets[index % len(expiry_offsets)]
        exceptions.append(
            PolicyException(
                exception_id=f"exc-{index}",
                scope=ExceptionScope(
                    action_type="approve_vendor_payment",
                    actor="fin-1",
                    attributes={"vendor_verified": True},
                ),
                expiry=now + timedelta(days=expiry_offset),
                approver_class="finance_director",
                justification="property test",
                approved_by="director-1" if approved else None,
                approved_at=now if approved else None,
            )
        )

    evaluator = PolicyEvaluator(
        [allow_rule],
        invariants=[invariant],
        exceptions=exceptions,
        config=EvaluatorConfig(deterministic_mode=True),
    )
    proposal = ActionProposal(
        action_type="approve_vendor_payment",
        actor_id="fin-1",
        attributes={"impact_scope": "production", "vendor_verified": True},
    )

    trace = evaluator.evaluate(proposal, {})

    assert trace.baseline_outcome == DecisionOutcome.BLOCKED
    assert trace.outcome == DecisionOutcome.BLOCKED
    assert all(
        result.changed_outcome is False for result in trace.evaluated_exceptions
    )
