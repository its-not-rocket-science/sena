import json

from sena.audit.chain import append_audit_record, verify_audit_chain
from sena.core.enums import DecisionOutcome, RuleDecision, Severity
from sena.core.models import ActionProposal, EvaluatorConfig, PolicyBundleMetadata, PolicyRule
from sena.engine.evaluator import PolicyEvaluator
from sena.policy.validation import PolicyValidationError, validate_condition


def test_audit_chain_verification_detects_tamper(tmp_path) -> None:
    sink = tmp_path / "audit.jsonl"
    append_audit_record(str(sink), {"decision_id": "d1", "outcome": "APPROVED"})
    append_audit_record(str(sink), {"decision_id": "d2", "outcome": "BLOCKED"})
    ok = verify_audit_chain(str(sink))
    assert ok["valid"] is True

    lines = sink.read_text().splitlines()
    tampered = json.loads(lines[1])
    tampered["outcome"] = "APPROVED"
    lines[1] = json.dumps(tampered)
    sink.write_text("\n".join(lines) + "\n")

    broken = verify_audit_chain(str(sink))
    assert broken["valid"] is False


def test_extended_dsl_validation_and_context_schema_block() -> None:
    validate_condition({"field": "email", "matches_regex": ".+@example\\.com"})
    with_exception = False
    try:
        validate_condition({"field": "amount", "between": [0]})
    except PolicyValidationError:
        with_exception = True
    assert with_exception is True

    rule = PolicyRule(
        id="allow_refund",
        description="allow",
        severity=Severity.LOW,
        inviolable=False,
        applies_to=["refund"],
        condition={"field": "amount", "lt": 20},
        decision=RuleDecision.ALLOW,
        reason="ok",
    )
    bundle = PolicyBundleMetadata(
        bundle_name="b",
        version="1",
        loaded_from="tmp",
        context_schema={"amount": "int", "request.region": "str"},
    )
    evaluator = PolicyEvaluator(
        [rule],
        policy_bundle=bundle,
        config=EvaluatorConfig(default_decision=DecisionOutcome.APPROVED),
    )
    trace = evaluator.evaluate(
        ActionProposal(action_type="refund", attributes={"amount": 10}),
        facts={},
    )
    assert trace.outcome == DecisionOutcome.BLOCKED
    assert "schema" in trace.reasoning.precedence_explanation.lower()
