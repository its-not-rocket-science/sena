import json

from sena.services.policy_analytics import PolicyEfficacyAnalytics


def test_policy_efficacy_analytics_aggregates_outcomes_and_incidents(tmp_path) -> None:
    audit_path = tmp_path / "audit.jsonl"
    audit_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "decision_id": "d-1",
                        "outcome": "APPROVED",
                        "policy_bundle": {"bundle_name": "enterprise-demo", "version": "2026.03"},
                        "downstream_outcome": "success",
                        "incident_flag": False,
                    }
                ),
                json.dumps(
                    {
                        "decision_id": "d-2",
                        "outcome": "BLOCKED",
                        "policy_bundle": {"bundle_name": "enterprise-demo", "version": "2026.03"},
                        "downstream_outcome": "failure",
                        "incident_flag": True,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = PolicyEfficacyAnalytics(str(audit_path)).compute()

    assert payload["generated_from_records"] == 2
    assert payload["totals"]["downstream_success"] == 1
    assert payload["totals"]["downstream_failure"] == 1
    assert payload["totals"]["incident_count"] == 1
    assert payload["policy_bundles"][0]["policy_bundle"] == "enterprise-demo:2026.03"
    assert payload["dashboard_example"]["title"] == "Policy Efficacy Overview"
