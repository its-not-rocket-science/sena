from __future__ import annotations

import hashlib
import json

from sena.core.enums import ActionOrigin, RuleDecision, Severity
from sena.core.models import AIActionMetadata, ActionProposal, PolicyRule
from sena.engine.evaluator import PolicyEvaluator


def _rules() -> list[PolicyRule]:
    return [
        PolicyRule(
            id="allow_basic",
            description="allow baseline",
            severity=Severity.MEDIUM,
            inviolable=False,
            applies_to=["deploy"],
            condition={"field": "risk", "eq": "low"},
            decision=RuleDecision.ALLOW,
            reason="baseline allow",
            control_ids=["ctrl-1"],
        )
    ]


def test_characterization_hash_inputs_remain_contract_stable() -> None:
    evaluator = PolicyEvaluator(_rules())
    proposal = ActionProposal(
        action_type="deploy",
        request_id="req-1",
        actor_id="actor-1",
        actor_role="engineer",
        action_origin=ActionOrigin.AI_SUGGESTED,
        ai_metadata=AIActionMetadata(originating_system="assistant", human_owner="owner-1"),
        attributes={
            "risk": "low",
            "change_ticket_id": "chg-1",
            "simulation_preview_ref": "sim-1",
            "rollback_plan_ref": "rb-1",
        },
    )

    trace = evaluator.evaluate(proposal, {"fact": "x"})

    expected_input_fingerprint = hashlib.sha256(
        json.dumps(
            {
                "proposal": {
                    "action_type": "deploy",
                    "request_id": "req-1",
                    "actor_id": "actor-1",
                    "actor_role": "engineer",
                    "attributes": proposal.attributes,
                    "action_origin": "ai_suggested",
                    "ai_metadata": {
                        "originating_system": "assistant",
                        "originating_model": None,
                        "prompt_context_ref": None,
                        "confidence": None,
                        "uncertainty": None,
                        "requested_tool": None,
                        "requested_action": None,
                        "evidence_references": [],
                        "citation_references": [],
                        "human_requester": None,
                        "human_owner": "owner-1",
                        "human_approver": None,
                        "risk_classification": None,
                    },
                    "autonomous_metadata": None,
                },
                "facts": {"fact": "x"},
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    assert trace.reasoning is not None
    assert trace.reasoning.provenance["input_fingerprint"] == expected_input_fingerprint
    assert trace.canonical_replay_payload["input_fingerprint"] == expected_input_fingerprint
    assert trace.audit_record is not None
    assert trace.audit_record.input_fingerprint == expected_input_fingerprint


def test_characterization_precedence_steps_are_stable_and_ordered() -> None:
    evaluator = PolicyEvaluator(_rules())
    trace = evaluator.evaluate(
        ActionProposal(action_type="deploy", attributes={"risk": "none"}), {}
    )

    stages = [step.stage for step in trace.precedence_steps]
    assert stages[0] == "start"
    assert "rule_evaluation" in stages
    assert stages[-1] in {"default_precedence", "strict_allow_guardrail", "conflict_resolution"}
