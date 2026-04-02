import json

from sena.core.enums import ActionOrigin
from sena.core.models import ActionProposal
from sena.engine.evaluator import PolicyEvaluator
from sena.engine.replay import build_drift_report, evaluate_replay_cases, load_replay_cases
from sena.policy.parser import load_policy_bundle


def test_replay_drift_from_proposal_and_trace_is_deterministic() -> None:
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    evaluator = PolicyEvaluator(rules, policy_bundle=metadata)
    trace = evaluator.evaluate(
        ActionProposal(
            action_type="approve_vendor_payment",
            request_id="req-trace",
            actor_id="actor-1",
            actor_role="finance_analyst",
            attributes={"amount": 20000, "vendor_verified": True, "source_system": "jira"},
        ),
        {},
    )
    payload = {
        "cases": [
            {
                "case_id": "proposal_case",
                "proposal": {
                    "action_type": "approve_vendor_payment",
                    "request_id": "req-proposal",
                    "actor_id": "actor-1",
                    "actor_role": "finance_analyst",
                    "attributes": {"amount": 500, "vendor_verified": True, "source_system": "jira"},
                    "action_origin": ActionOrigin.HUMAN.value,
                },
            },
            {"case_id": "trace_case", "trace": trace.to_dict()},
        ]
    }

    cases = load_replay_cases(payload)
    before = evaluate_replay_cases(cases=cases, rules=rules, metadata=metadata)
    after = evaluate_replay_cases(cases=cases, rules=rules, metadata=metadata)
    report = build_drift_report(
        cases=cases,
        baseline=before,
        candidate=after,
        baseline_label="baseline",
        candidate_label="candidate",
    )

    assert report["total_cases"] == 2
    assert report["changed_outcomes"] == 0
    assert report["changed_matched_controls"] == 0
    assert report["changed_missing_evidence"] == 0
    assert report["escalation_rates"]["delta"] == 0.0
    assert json.dumps(report)


def test_replay_drift_detects_mapping_changes(tmp_path) -> None:
    baseline_mapping = tmp_path / "baseline_webhook_mapping.yaml"
    candidate_mapping = tmp_path / "candidate_webhook_mapping.yaml"
    baseline_mapping.write_text(
        """
providers:
  stripe:
    invoice.created:
      action_type: approve_vendor_payment
      actor_id_path: owner.id
      attributes:
        amount: amount
        vendor_verified: vendor_verified
""".strip()
    )
    candidate_mapping.write_text(
        """
providers:
  stripe:
    invoice.created:
      action_type: release_refund
      actor_id_path: owner.id
      attributes:
        amount: amount
        order_exists: order_exists
""".strip()
    )
    replay_payload = {
        "cases": [
            {
                "case_id": "webhook_case",
                "event": {
                    "provider": "stripe",
                    "event_type": "invoice.created",
                    "default_request_id": "inv-1",
                    "payload": {
                        "id": "evt_1",
                        "owner": {"id": "automation-bot"},
                        "amount": 6000,
                        "vendor_verified": False,
                        "order_exists": True,
                    },
                },
            }
        ]
    }
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    baseline_cases = load_replay_cases(
        replay_payload,
        mapping_mode="webhook",
        mapping_config_path=str(baseline_mapping),
    )
    candidate_cases = load_replay_cases(
        replay_payload,
        mapping_mode="webhook",
        mapping_config_path=str(candidate_mapping),
    )
    baseline = evaluate_replay_cases(cases=baseline_cases, rules=rules, metadata=metadata)
    candidate = evaluate_replay_cases(cases=candidate_cases, rules=rules, metadata=metadata)
    report = build_drift_report(
        cases=baseline_cases,
        baseline=baseline,
        candidate=candidate,
        baseline_label="baseline-map",
        candidate_label="candidate-map",
    )

    assert report["changed_outcomes"] == 1
    assert report["changed_matched_controls"] == 1
