from __future__ import annotations

from sena.engine.parallel import run_parallel_mode
from sena.engine.replay import load_replay_cases
from sena.policy.parser import load_policy_bundle


def test_parallel_run_reports_discrepancies() -> None:
    replay_payload = {
        "cases": [
            {
                "case_id": "refund_case",
                "proposal": {
                    "action_type": "release_refund",
                    "request_id": "req-1",
                    "actor_id": "ops-1",
                    "actor_role": "support",
                    "attributes": {
                        "amount": 750,
                        "order_exists": True,
                        "delivery_failed": True,
                    },
                },
                "source_system": "jira",
                "workflow_stage": "pre-approval",
                "risk_category": "payments",
            }
        ]
    }
    cases = load_replay_cases(replay_payload)
    old_rules, old_meta = load_policy_bundle("src/sena/examples/policies")
    new_rules = old_rules[:-1]

    report = run_parallel_mode(
        cases=cases,
        old_rules=old_rules,
        old_metadata=old_meta,
        new_rules=new_rules,
        new_metadata=old_meta,
    )

    assert report["report_type"] == "sena.parallel_run_discrepancy_report"
    assert report["mode"] == "parallel"
    assert report["total_cases"] == 1
    assert report["discrepancy_summary"]["outcome_changes"] >= 0
    assert len(report["discrepancies"]) == 1
