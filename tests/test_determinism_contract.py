from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sena.core.enums import ActionOrigin, DecisionOutcome, RuleDecision, Severity
from sena.core.models import (
    ActionProposal,
    EvaluatorConfig,
    ExceptionScope,
    PolicyBundleMetadata,
    PolicyException,
    PolicyInvariant,
    PolicyRule,
)
from sena.engine.evaluator import PolicyEvaluator
from sena.policy.parser import load_policy_bundle


def _rule(
    rule_id: str,
    *,
    decision: RuleDecision,
    condition: dict[str, object] | None = None,
    inviolable: bool = False,
    required_evidence: list[str] | None = None,
    missing_evidence_decision: RuleDecision | None = None,
) -> PolicyRule:
    return PolicyRule(
        id=rule_id,
        description=f"rule {rule_id}",
        severity=Severity.MEDIUM,
        inviolable=inviolable,
        applies_to=["approve_vendor_payment"],
        condition=condition or {"field": "amount", "gte": 1000},
        decision=decision,
        reason=f"{rule_id} matched",
        required_evidence=required_evidence or [],
        missing_evidence_decision=missing_evidence_decision,
    )


def test_semantic_payload_key_ordering_produces_stable_hashes_and_ids() -> None:
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    evaluator = PolicyEvaluator(
        rules,
        policy_bundle=metadata,
        config=EvaluatorConfig(deterministic_mode=True),
    )

    proposal_a = ActionProposal(
        action_type="approve_vendor_payment",
        request_id="req-key-order",
        actor_id="alice",
        actor_role="finance_analyst",
        attributes={
            "amount": 2_500,
            "vendor_verified": True,
            "risk_attributes": {"tier": "low", "region": "us"},
        },
    )
    proposal_b = ActionProposal(
        action_type="approve_vendor_payment",
        request_id="req-key-order",
        actor_id="alice",
        actor_role="finance_analyst",
        attributes={
            "risk_attributes": {"region": "us", "tier": "low"},
            "vendor_verified": True,
            "amount": 2_500,
        },
    )
    facts_a = {"geo": "us", "risk_score": 4, "signals": {"source": "erp", "band": "L"}}
    facts_b = {"signals": {"band": "L", "source": "erp"}, "risk_score": 4, "geo": "us"}

    first = evaluator.evaluate(proposal_a, facts_a)
    second = evaluator.evaluate(proposal_b, facts_b)

    first_bytes = json.dumps(
        first.canonical_replay_payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    second_bytes = json.dumps(
        second.canonical_replay_payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")

    assert first.outcome == second.outcome
    assert first.decision_hash == second.decision_hash
    assert first.decision_id == second.decision_id
    assert first.canonical_replay_payload["matched_rule_ids"] == second.canonical_replay_payload[
        "matched_rule_ids"
    ]
    assert (
        first.canonical_replay_payload["precedence_steps"]
        == second.canonical_replay_payload["precedence_steps"]
    )
    assert first_bytes == second_bytes


def test_policy_bundle_file_ordering_does_not_change_outcome_or_replay_payload(
    tmp_path,
) -> None:
    bundle_a = tmp_path / "bundle_a"
    bundle_b = tmp_path / "bundle_b"
    bundle_a.mkdir()
    bundle_b.mkdir()

    rule_one = """
- id: block-high
  description: Block high amounts.
  severity: high
  inviolable: false
  applies_to: [approve_vendor_payment]
  condition: { field: amount, gte: 1000 }
  decision: BLOCK
  reason: Block amount.
""".strip()
    rule_two = """
- id: allow-vendor
  description: Allow known vendor.
  severity: medium
  inviolable: false
  applies_to: [approve_vendor_payment]
  condition: { field: vendor_verified, eq: true }
  decision: ALLOW
  reason: Allow vendor.
""".strip()
    (bundle_a / "10-first.yaml").write_text(rule_one, encoding="utf-8")
    (bundle_a / "20-second.yaml").write_text(rule_two, encoding="utf-8")
    (bundle_b / "10-first.yaml").write_text(rule_two, encoding="utf-8")
    (bundle_b / "20-second.yaml").write_text(rule_one, encoding="utf-8")

    rules_a, metadata_a = load_policy_bundle(bundle_a, bundle_name="bundle", version="1")
    rules_b, metadata_b = load_policy_bundle(bundle_b, bundle_name="bundle", version="1")
    evaluator_a = PolicyEvaluator(rules_a, policy_bundle=metadata_a)
    evaluator_b = PolicyEvaluator(rules_b, policy_bundle=metadata_b)

    proposal = ActionProposal(
        action_type="approve_vendor_payment",
        request_id="req-order",
        actor_id="alice",
        actor_role="finance_analyst",
        attributes={"amount": 2_500, "vendor_verified": True},
    )

    first = evaluator_a.evaluate(proposal, {})
    second = evaluator_b.evaluate(proposal, {})

    assert first.outcome == second.outcome
    assert first.decision_hash == second.decision_hash
    assert first.canonical_replay_payload == second.canonical_replay_payload


def test_missing_evidence_for_ai_actions_is_deterministically_blocking() -> None:
    evaluator = PolicyEvaluator(
        [
            _rule(
                "ai-evidence",
                decision=RuleDecision.ALLOW,
                condition={"field": "amount", "gte": 1},
                required_evidence=["source_citations", "human_owner"],
                missing_evidence_decision=RuleDecision.BLOCK,
            )
        ]
    )
    proposal = ActionProposal(
        action_type="approve_vendor_payment",
        request_id="req-evidence",
        actor_id="ai-assistant",
        actor_role="assistant",
        action_origin=ActionOrigin.AI_SUGGESTED,
        attributes={"amount": 5000},
    )

    trace = evaluator.evaluate(proposal, {})

    assert trace.outcome == DecisionOutcome.BLOCKED
    assert trace.matched_rules[0].missing_evidence == ["source_citations", "human_owner"]
    assert "evidence.source_citations" in trace.missing_fields
    assert "evidence.human_owner" in trace.missing_fields


def test_invariant_and_allow_conflict_is_blocked_with_invariant_precedence() -> None:
    invariant = PolicyInvariant(
        id="inv-1",
        description="No production deploys in freeze",
        applies_to=["approve_vendor_payment"],
        condition={"field": "freeze_window", "eq": True},
        reason="freeze window",
    )
    evaluator = PolicyEvaluator(
        [_rule("allow-1", decision=RuleDecision.ALLOW)],
        invariants=[invariant],
        policy_bundle=PolicyBundleMetadata(
            bundle_name="bundle",
            version="1",
            loaded_from="tests",
            invariants=[invariant],
        ),
    )
    proposal = ActionProposal(
        action_type="approve_vendor_payment",
        attributes={"amount": 1500, "freeze_window": True},
    )

    trace = evaluator.evaluate(proposal, {})

    assert trace.outcome == DecisionOutcome.BLOCKED
    assert [step.stage for step in trace.precedence_steps].count("invariant_precedence") == 1
    assert trace.canonical_replay_payload["matched_invariant_ids"] == ["inv-1"]


def test_conflicting_rule_matches_resolve_with_stable_precedence() -> None:
    evaluator = PolicyEvaluator(
        [
            _rule("allow-1", decision=RuleDecision.ALLOW),
            _rule("escalate-1", decision=RuleDecision.ESCALATE),
            _rule("block-1", decision=RuleDecision.BLOCK),
        ]
    )
    proposal = ActionProposal(
        action_type="approve_vendor_payment",
        attributes={"amount": 1500},
    )

    first = evaluator.evaluate(proposal, {})
    second = evaluator.evaluate(proposal, {})

    assert first.outcome == DecisionOutcome.BLOCKED
    assert first.conflicting_rules == ["block-1"]
    assert first.canonical_replay_payload["matched_rule_ids"] == [
        "allow-1",
        "block-1",
        "escalate-1",
    ]
    assert first.canonical_replay_payload["precedence_steps"] == second.canonical_replay_payload[
        "precedence_steps"
    ]


def test_exception_overlay_with_multiple_matches_is_stable() -> None:
    now = datetime.now(timezone.utc)
    exceptions = [
        PolicyException(
            exception_id="exc-b",
            scope=ExceptionScope(action_type="approve_vendor_payment"),
            expiry=now + timedelta(hours=2),
            approver_class="security",
            justification="temporary",
            approved_by="approver",
            approved_at=now - timedelta(minutes=5),
        ),
        PolicyException(
            exception_id="exc-a",
            scope=ExceptionScope(action_type="approve_vendor_payment"),
            expiry=now + timedelta(hours=2),
            approver_class="security",
            justification="temporary",
            approved_by="approver",
            approved_at=now - timedelta(minutes=5),
        ),
    ]
    evaluator = PolicyEvaluator(
        [_rule("escalate-1", decision=RuleDecision.ESCALATE)],
        exceptions=exceptions,
    )
    proposal = ActionProposal(
        action_type="approve_vendor_payment",
        attributes={"amount": 1500},
    )

    first = evaluator.evaluate(proposal, {})
    second = evaluator.evaluate(proposal, {})

    assert first.baseline_outcome == DecisionOutcome.ESCALATE_FOR_HUMAN_REVIEW
    assert first.outcome == DecisionOutcome.APPROVED
    assert [item.exception_id for item in first.applied_exceptions] == ["exc-a", "exc-b"]
    assert [item.exception_id for item in second.applied_exceptions] == ["exc-a", "exc-b"]
    assert first.canonical_replay_payload["precedence_steps"] == second.canonical_replay_payload[
        "precedence_steps"
    ]
