from sena.api.schemas import EvaluateRequest
from sena.core.enums import ActionOrigin, DecisionOutcome
from sena.core.models import AIActionMetadata, ActionProposal, RiskClassification
from sena.engine.evaluator import PolicyEvaluator
from sena.engine.review_package import build_decision_review_package
from sena.policy.parser import load_policy_bundle


def _evaluator() -> PolicyEvaluator:
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    return PolicyEvaluator(rules, policy_bundle=metadata)


def test_ai_suggested_actions_require_governance_fields() -> None:
    evaluator = _evaluator()
    trace = evaluator.evaluate(
        ActionProposal(
            action_type="approve_vendor_payment",
            action_origin=ActionOrigin.AI_SUGGESTED,
            actor_id="fin-1",
            actor_role="finance_analyst",
            attributes={"amount": 400, "vendor_verified": True},
        ),
        facts={},
    )

    assert trace.outcome == DecisionOutcome.BLOCKED
    assert "ai_metadata.originating_system" in trace.missing_fields
    assert "ai-governance" in trace.summary.lower()


def test_ai_suggested_actions_evaluate_deterministically_when_fields_present() -> None:
    evaluator = _evaluator()
    trace = evaluator.evaluate(
        ActionProposal(
            action_type="approve_vendor_payment",
            action_origin=ActionOrigin.AI_SUGGESTED,
            actor_id="fin-1",
            actor_role="finance_analyst",
            attributes={"amount": 400, "vendor_verified": True},
            ai_metadata=AIActionMetadata(
                originating_system="copilot",
                originating_model="gpt-5.3-codex",
                prompt_context_ref="policy://approvals/v3",
                confidence=0.62,
                uncertainty="supplier not in preferred catalog",
                requested_tool="payments_api",
                requested_action="approve_vendor_payment",
                evidence_references=["evidence://vendor/123"],
                citation_references=["doc://controls/fin-12"],
                human_requester="requester-7",
                human_owner="fin-risk-owner",
                human_approver="director-2",
                risk_classification=RiskClassification(
                    category="financial_disbursement",
                    level="medium",
                    tags=["vendor", "invoice"],
                ),
            ),
        ),
        facts={},
    )

    assert trace.outcome == DecisionOutcome.APPROVED
    package = build_decision_review_package(trace)
    assert (
        package["facts_and_actor"]["request_origin"]["classification"] == "ai_suggested"
    )
    assert (
        package["facts_and_actor"]["request_origin"]["ai_metadata"][
            "originating_system"
        ]
        == "copilot"
    )


def test_ai_assisted_high_risk_action_blocks_when_evidence_bundle_is_incomplete() -> (
    None
):
    evaluator = _evaluator()
    trace = evaluator.evaluate(
        ActionProposal(
            action_type="approve_vendor_payment",
            action_origin=ActionOrigin.AI_SUGGESTED,
            actor_id="fin-1",
            actor_role="finance_analyst",
            attributes={"amount": 400, "vendor_verified": True},
            ai_metadata=AIActionMetadata(
                originating_system="copilot",
                originating_model="gpt-5.3-codex",
                prompt_context_ref="policy://approvals/v3",
                requested_action="approve_vendor_payment",
                evidence_references=["evidence://vendor/123"],
                citation_references=["doc://controls/fin-12"],
                human_requester="requester-7",
                human_owner="fin-risk-owner",
                risk_classification=RiskClassification(
                    category="financial_disbursement",
                    level="high",
                ),
            ),
        ),
        facts={},
    )

    assert trace.outcome == DecisionOutcome.BLOCKED
    assert "evidence.change_ticket" in trace.missing_fields
    package = build_decision_review_package(trace)
    assert "change_ticket" in package["governance_evidence"]["missing_evidence_classes"]


def test_evaluate_request_schema_requires_ai_metadata_for_ai_origin() -> None:
    try:
        EvaluateRequest(
            action_type="approve_vendor_payment",
            request_id="req-1",
            action_origin=ActionOrigin.AI_SUGGESTED,
            attributes={"amount": 5, "vendor_verified": True},
        )
    except ValueError as exc:
        assert "requires ai_metadata" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected schema validation failure")
