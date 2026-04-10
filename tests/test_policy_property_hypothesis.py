from __future__ import annotations

import json
from pathlib import Path
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from itertools import permutations

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from sena.core.enums import (  # noqa: E402
    ActionOrigin,
    DecisionOutcome,
    RuleDecision,
    Severity,
)
from sena.core.models import (  # noqa: E402
    ActionProposal,
    ExceptionScope,
    EvaluatorConfig,
    PolicyException,
    PolicyInvariant,
    PolicyRule,
)
from sena.engine.evaluator import PolicyEvaluator  # noqa: E402
from sena.policy.grammar import COMPARISON_OPERATORS, LOGICAL_OPERATORS  # noqa: E402
from sena.policy.interpreter import evaluate_condition_with_trace  # noqa: E402
from sena.policy.parser import PolicyParseError, parse_policy_file  # noqa: E402


SAFE_HYPOTHESIS_SETTINGS = settings(
    max_examples=120,
    derandomize=True,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


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
    ).filter(
        lambda name: name
        not in (COMPARISON_OPERATORS | LOGICAL_OPERATORS | {"field"})
    ),
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
    assert permuted.canonical_replay_payload == canonical.canonical_replay_payload
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


@SAFE_HYPOTHESIS_SETTINGS
@given(
    decision_order=st.sampled_from(
        [
            (RuleDecision.ALLOW, RuleDecision.ESCALATE, RuleDecision.BLOCK),
            (RuleDecision.BLOCK, RuleDecision.ALLOW, RuleDecision.ESCALATE),
            (RuleDecision.ESCALATE, RuleDecision.BLOCK, RuleDecision.ALLOW),
        ]
    )
)
def test_conflicting_matched_rules_have_stable_precedence_and_conflict_ids(
    decision_order: tuple[RuleDecision, RuleDecision, RuleDecision],
) -> None:
    rules = [
        PolicyRule(
            id=f"conflict_{idx}",
            description=f"conflicting rule {idx}",
            severity=Severity.MEDIUM,
            inviolable=False,
            applies_to=["approve_vendor_payment"],
            condition={"field": "country", "eq": "us"},
            decision=decision,
            reason=f"decision {decision.value}",
        )
        for idx, decision in enumerate(decision_order)
    ]
    proposal = ActionProposal(
        action_type="approve_vendor_payment",
        attributes={"country": "us"},
    )
    outcomes: set[DecisionOutcome] = set()
    conflict_vectors: set[tuple[str, ...]] = set()

    for order in permutations(rules):
        trace = PolicyEvaluator(
            list(order),
            config=EvaluatorConfig(deterministic_mode=True),
        ).evaluate(proposal, {})
        outcomes.add(trace.outcome)
        conflict_vectors.add(tuple(trace.conflicting_rules))
        assert "conflict_resolution" in {
            step["stage"]
            for step in trace.canonical_replay_payload["precedence_steps"]
            if isinstance(step, dict)
        }

    assert outcomes == {DecisionOutcome.BLOCKED}
    assert all(vector for vector in conflict_vectors)


@SAFE_HYPOTHESIS_SETTINGS
@given(
    include_citations=st.booleans(),
    include_owner=st.booleans(),
)
def test_missing_evidence_changes_only_evidence_sensitive_rule_path(
    include_citations: bool,
    include_owner: bool,
) -> None:
    rules = [
        PolicyRule(
            id="allow_verified_vendor",
            description="allow verified vendor",
            severity=Severity.LOW,
            inviolable=False,
            applies_to=["approve_vendor_payment"],
            condition={"field": "vendor_verified", "eq": True},
            decision=RuleDecision.ALLOW,
            reason="vendor verified",
            required_evidence=["source_citations", "human_owner"],
            missing_evidence_decision=RuleDecision.ESCALATE,
        ),
        PolicyRule(
            id="allow_small_amount",
            description="allow small amount",
            severity=Severity.LOW,
            inviolable=False,
            applies_to=["approve_vendor_payment"],
            condition={"field": "amount", "lte": 500},
            decision=RuleDecision.ALLOW,
            reason="small amount",
        ),
    ]
    base_attrs = {
        "vendor_verified": True,
        "amount": 100,
    }
    with_evidence = ActionProposal(
        action_type="approve_vendor_payment",
        action_origin=ActionOrigin.AI_SUGGESTED,
        attributes={
            **base_attrs,
            "ai_metadata": {
                "citation_references": ["doc-1"] if include_citations else [],
                "human_owner": "ops-1" if include_owner else "",
            },
        },
    )
    without_evidence = ActionProposal(
        action_type="approve_vendor_payment",
        action_origin=ActionOrigin.AI_SUGGESTED,
        attributes=base_attrs,
    )
    evaluator = PolicyEvaluator(
        rules,
        config=EvaluatorConfig(deterministic_mode=True),
    )
    trace_with = evaluator.evaluate(with_evidence, {})
    trace_without = evaluator.evaluate(without_evidence, {})
    by_id_with = {item.rule_id: item for item in trace_with.evaluated_rules}
    by_id_without = {item.rule_id: item for item in trace_without.evaluated_rules}

    assert by_id_with["allow_small_amount"].decision == RuleDecision.ALLOW
    assert by_id_without["allow_small_amount"].decision == RuleDecision.ALLOW
    assert by_id_with["allow_small_amount"].missing_evidence == []
    assert by_id_without["allow_small_amount"].missing_evidence == []

    expected_missing: list[str] = []
    if not include_citations:
        expected_missing.append("source_citations")
    if not include_owner:
        expected_missing.append("human_owner")
    assert sorted(by_id_with["allow_verified_vendor"].missing_evidence) == sorted(
        expected_missing
    )
    assert sorted(by_id_without["allow_verified_vendor"].missing_evidence) == [
        "human_owner",
        "source_citations",
    ]


@SAFE_HYPOTHESIS_SETTINGS
@given(
    amount=st.integers(min_value=1, max_value=2000),
    vendor_verified=st.booleans(),
)
def test_canonical_replay_payload_excludes_volatile_fields_by_construction(
    amount: int, vendor_verified: bool
) -> None:
    rules = [
        PolicyRule(
            id="allow_verified",
            description="allow verified vendors",
            severity=Severity.LOW,
            inviolable=False,
            applies_to=["approve_vendor_payment"],
            condition={"field": "vendor_verified", "eq": True},
            decision=RuleDecision.ALLOW,
            reason="verified",
        )
    ]
    proposal = ActionProposal(
        action_type="approve_vendor_payment",
        request_id="req-1",
        actor_id="actor-1",
        attributes={"amount": amount, "vendor_verified": vendor_verified},
    )
    trace = PolicyEvaluator(
        rules, config=EvaluatorConfig(deterministic_mode=True)
    ).evaluate(proposal, {})
    payload = trace.canonical_replay_payload
    payload_json = json.dumps(payload, sort_keys=True)

    assert "decision_timestamp" not in payload
    assert "decision_id" not in payload
    assert "operational_metadata" not in payload
    assert "decision_timestamp" not in payload_json
    assert "dec_" not in payload_json
