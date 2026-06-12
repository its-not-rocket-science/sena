from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from sena.core.enums import ActionOrigin
from sena.core.models import (
    AIActionMetadata,
    ActionProposal,
    ExceptionScope,
    PolicyException,
    RiskClassification,
)
from sena.engine.evaluator import PolicyEvaluator
from sena.integrations.jira import (
    AllowAllJiraWebhookVerifier,
    JiraConnector,
    load_jira_mapping_config,
)
from sena.integrations.servicenow import (
    ServiceNowConnector,
    load_servicenow_mapping_config,
)
from sena.policy.parser import load_policy_bundle

_FIXTURE_DIR = Path("tests/replay_corpus/fixtures/scenarios")


class ReplayFixtureError(ValueError):
    """Raised when a replay fixture is malformed."""


def load_replay_fixtures() -> list[dict[str, Any]]:
    fixtures: list[dict[str, Any]] = []
    for fixture_path in sorted(_FIXTURE_DIR.glob("*.json")):
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        fixture["_fixture_path"] = str(fixture_path)
        fixtures.append(fixture)
    if not fixtures:
        raise ReplayFixtureError(f"No replay fixtures found under {_FIXTURE_DIR}")
    return fixtures


def _parse_ai_metadata(ai_payload: dict[str, Any] | None) -> AIActionMetadata | None:
    if not isinstance(ai_payload, dict):
        return None
    normalized_ai_payload = dict(ai_payload)
    risk_payload = normalized_ai_payload.get("risk_classification")
    if isinstance(risk_payload, dict):
        normalized_ai_payload["risk_classification"] = RiskClassification(**risk_payload)
    return AIActionMetadata(**normalized_ai_payload)


def _proposal_from_payload(payload: dict[str, Any]) -> ActionProposal:
    return ActionProposal(
        action_type=payload["action_type"],
        request_id=payload.get("request_id"),
        actor_id=payload.get("actor_id"),
        actor_role=payload.get("actor_role"),
        attributes=dict(payload.get("attributes") or {}),
        action_origin=ActionOrigin(payload.get("action_origin", "human")),
        ai_metadata=_parse_ai_metadata(payload.get("ai_metadata")),
    )


def _exceptions_from_fixture(fixture: dict[str, Any]) -> list[PolicyException]:
    parsed: list[PolicyException] = []
    for payload in fixture.get("exceptions", []):
        parsed.append(
            PolicyException(
                exception_id=payload["exception_id"],
                scope=ExceptionScope(**payload["scope"]),
                expiry=datetime.fromisoformat(payload["expiry"]),
                approver_class=payload["approver_class"],
                justification=payload["justification"],
                approved_by=payload.get("approved_by"),
                approved_at=datetime.fromisoformat(payload["approved_at"])
                if payload.get("approved_at")
                else None,
            )
        )
    return parsed


def _event_payload(event_fixture_path: str) -> dict[str, Any]:
    return json.loads(Path(event_fixture_path).read_text(encoding="utf-8"))


def _proposal_from_mapped_event(input_payload: dict[str, Any]) -> ActionProposal:
    source = input_payload["source_system"]
    event_payload = _event_payload(input_payload["event_fixture_path"])
    headers = input_payload.get("headers") or {}

    if source == "jira":
        connector = JiraConnector(
            config=load_jira_mapping_config("src/sena/examples/integrations/jira_mappings.yaml"),
            verifier=AllowAllJiraWebhookVerifier(),
        )
        mapped = connector.handle_event(
            {
                "headers": headers,
                "payload": event_payload,
                "raw_body": json.dumps(event_payload).encode("utf-8"),
            }
        )
        return mapped["action_proposal"]

    if source == "servicenow":
        connector = ServiceNowConnector(
            config=load_servicenow_mapping_config(
                "src/sena/examples/integrations/servicenow_mappings.yaml"
            )
        )
        mapped = connector.handle_event(
            {
                "headers": headers,
                "payload": event_payload,
                "raw_body": json.dumps(event_payload).encode("utf-8"),
            }
        )
        return mapped["action_proposal"]

    raise ReplayFixtureError(f"Unsupported mapped source_system '{source}'")


def _proposal_from_fixture(fixture: dict[str, Any]) -> ActionProposal:
    input_payload = fixture.get("input")
    if not isinstance(input_payload, dict):
        raise ReplayFixtureError("fixture.input must be an object")

    mode = input_payload.get("mode")
    if mode == "normalized_proposal":
        proposal_payload = input_payload.get("proposal")
        if not isinstance(proposal_payload, dict):
            raise ReplayFixtureError("normalized_proposal requires input.proposal")
        return _proposal_from_payload(proposal_payload)
    if mode == "mapped_event":
        return _proposal_from_mapped_event(input_payload)

    raise ReplayFixtureError(f"Unsupported fixture input mode '{mode}'")


def evaluate_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    if fixture.get("fixture_schema") != "sena.replay_fixture.v1":
        raise ReplayFixtureError(
            "fixture_schema must be 'sena.replay_fixture.v1' "
            f"(got {fixture.get('fixture_schema')!r})"
        )

    bundle = fixture.get("bundle") or {}
    bundle_path = bundle.get("path")
    if not isinstance(bundle_path, str):
        raise ReplayFixtureError("bundle.path is required")

    rules, metadata = load_policy_bundle(bundle_path)
    evaluator = PolicyEvaluator(
        rules,
        policy_bundle=metadata,
        exceptions=_exceptions_from_fixture(fixture),
    )

    proposal = _proposal_from_fixture(fixture)
    facts = dict((fixture.get("input") or {}).get("facts") or {})
    trace = evaluator.evaluate(proposal, facts)

    missing_evidence = sorted(
        {
            evidence
            for item in trace.matched_rules
            for evidence in item.missing_evidence
        }
    )
    actual = {
        "bundle_identity": {
            "name": trace.policy_bundle.bundle_name if trace.policy_bundle else None,
            "version": trace.policy_bundle.version if trace.policy_bundle else None,
        },
        "outcome": trace.outcome.value,
        "matched_rules": sorted(item.rule_id for item in trace.matched_rules),
        "missing_fields": sorted(trace.missing_fields),
        "missing_evidence": missing_evidence,
        "decision_hash": trace.decision_hash,
        "baseline_outcome": trace.baseline_outcome.value if trace.baseline_outcome else None,
        "applied_exception_ids": sorted(
            item.exception_id for item in trace.applied_exceptions
        ),
        "normalized_proposal": asdict(proposal),
    }
    return actual


def evaluate_all_fixtures() -> dict[str, dict[str, Any]]:
    outputs: dict[str, dict[str, Any]] = {}
    for fixture in load_replay_fixtures():
        case_id = str(fixture.get("case_id") or "")
        if not case_id:
            raise ReplayFixtureError(
                f"fixture at {fixture['_fixture_path']} is missing case_id"
            )
        outputs[case_id] = evaluate_fixture(fixture)
    return outputs


def build_drift_report() -> dict[str, Any]:
    mismatches: list[dict[str, Any]] = []
    semantic: dict[str, int] = {
        "outcome_changes": 0,
        "matched_rule_changes": 0,
        "missing_field_changes": 0,
        "decision_hash_changes": 0,
    }

    for fixture in load_replay_fixtures():
        case_id = str(fixture["case_id"])
        expected = fixture.get("expected")
        if not isinstance(expected, dict):
            raise ReplayFixtureError(f"fixture {case_id} is missing expected object")
        actual = evaluate_fixture(fixture)

        for field in [
            "bundle_identity",
            "outcome",
            "matched_rules",
            "missing_fields",
            "missing_evidence",
            "decision_hash",
            "baseline_outcome",
            "applied_exception_ids",
        ]:
            expected_value = expected.get(field)
            actual_value = actual.get(field)
            if expected_value != actual_value:
                mismatches.append(
                    {
                        "case_id": case_id,
                        "field": field,
                        "expected": expected_value,
                        "actual": actual_value,
                    }
                )
                if field == "outcome":
                    semantic["outcome_changes"] += 1
                elif field == "matched_rules":
                    semantic["matched_rule_changes"] += 1
                elif field == "missing_fields":
                    semantic["missing_field_changes"] += 1
                elif field == "decision_hash":
                    semantic["decision_hash_changes"] += 1

        expected_normalized = expected.get("normalized_proposal")
        if expected_normalized is not None and expected_normalized != actual["normalized_proposal"]:
            mismatches.append(
                {
                    "case_id": case_id,
                    "field": "normalized_proposal",
                    "expected": expected_normalized,
                    "actual": actual["normalized_proposal"],
                }
            )

    return {
        "schema": "sena.replay_drift_report.v1",
        "total_fixtures": len(load_replay_fixtures()),
        "mismatches": mismatches,
        "semantic_drift_summary": semantic,
    }


def refresh_fixture_expectations() -> list[str]:
    updated_paths: list[str] = []
    for fixture_path in sorted(_FIXTURE_DIR.glob("*.json")):
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        fixture["expected"] = evaluate_fixture(fixture)
        fixture_path.write_text(
            json.dumps(fixture, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        updated_paths.append(str(fixture_path))
    return updated_paths
