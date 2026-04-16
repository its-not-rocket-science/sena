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
from sena.integrations.jira import AllowAllJiraWebhookVerifier, JiraConnector, load_jira_mapping_config
from sena.integrations.servicenow import ServiceNowConnector, load_servicenow_mapping_config
from sena.policy.parser import load_policy_bundle

_CORPUS_PATH = Path("tests/replay_corpus/cases.json")
_BASELINE_PATH = Path("tests/replay_corpus/baselines/outcomes.json")


def load_corpus() -> dict[str, Any]:
    return json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))


def load_baseline() -> dict[str, Any]:
    return json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))


def write_baseline(payload: dict[str, Any]) -> None:
    _BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _BASELINE_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _proposal_from_case(case: dict[str, Any]) -> ActionProposal:
    proposal_payload = case["proposal"]
    ai_payload = proposal_payload.get("ai_metadata")
    ai_metadata = None
    if isinstance(ai_payload, dict):
        risk_payload = ai_payload.get("risk_classification")
        normalized_ai_payload = dict(ai_payload)
        if isinstance(risk_payload, dict):
            normalized_ai_payload["risk_classification"] = RiskClassification(**risk_payload)
        ai_metadata = AIActionMetadata(**normalized_ai_payload)
    return ActionProposal(
        action_type=proposal_payload["action_type"],
        request_id=proposal_payload.get("request_id"),
        actor_id=proposal_payload.get("actor_id"),
        actor_role=proposal_payload.get("actor_role"),
        attributes=dict(proposal_payload.get("attributes") or {}),
        action_origin=ActionOrigin(proposal_payload.get("action_origin", "human")),
        ai_metadata=ai_metadata,
    )


def _exceptions_from_case(case: dict[str, Any]) -> list[PolicyException]:
    parsed: list[PolicyException] = []
    for payload in case.get("exceptions", []):
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


def _event_payload(case: dict[str, Any]) -> dict[str, Any]:
    fixture_path = Path(case["fixture_path"])
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def _proposal_from_jira_event(case: dict[str, Any]) -> ActionProposal:
    connector = JiraConnector(
        config=load_jira_mapping_config("src/sena/examples/integrations/jira_mappings.yaml"),
        verifier=AllowAllJiraWebhookVerifier(),
    )
    payload = _event_payload(case)
    event = connector.handle_event(
        {
            "headers": case.get("headers") or {},
            "payload": payload,
            "raw_body": json.dumps(payload).encode("utf-8"),
        }
    )
    return event["action_proposal"]


def _proposal_from_servicenow_event(case: dict[str, Any]) -> ActionProposal:
    connector = ServiceNowConnector(
        config=load_servicenow_mapping_config(
            "src/sena/examples/integrations/servicenow_mappings.yaml"
        )
    )
    payload = _event_payload(case)
    event = connector.handle_event(
        {
            "headers": case.get("headers") or {},
            "payload": payload,
            "raw_body": json.dumps(payload).encode("utf-8"),
        }
    )
    return event["action_proposal"]


def evaluate_corpus_cases() -> dict[str, dict[str, Any]]:
    corpus = load_corpus()
    rules, metadata = load_policy_bundle(corpus["policy_bundle_path"])

    outcomes: dict[str, dict[str, Any]] = {}
    for case in corpus["cases"]:
        if case["kind"] == "proposal":
            proposal = _proposal_from_case(case)
        elif case["kind"] == "jira_event":
            proposal = _proposal_from_jira_event(case)
        elif case["kind"] == "servicenow_event":
            proposal = _proposal_from_servicenow_event(case)
        else:
            raise ValueError(f"Unsupported case kind: {case['kind']}")

        evaluator = PolicyEvaluator(
            rules,
            policy_bundle=metadata,
            exceptions=_exceptions_from_case(case),
        )
        trace = evaluator.evaluate(proposal, {})
        missing_evidence = sorted(
            {
                evidence
                for item in trace.matched_rules
                for evidence in item.missing_evidence
            }
        )
        outcomes[case["case_id"]] = {
            "scenario": case["scenario"],
            "outcome": trace.outcome.value,
            "decision_hash": trace.decision_hash,
            "matched_rule_ids": sorted(item.rule_id for item in trace.matched_rules),
            "missing_fields": sorted(trace.missing_fields),
            "missing_evidence": missing_evidence,
            "applied_exception_ids": sorted(
                item.exception_id for item in trace.applied_exceptions
            ),
            "baseline_outcome": trace.baseline_outcome.value
            if trace.baseline_outcome
            else None,
            "proposal": asdict(proposal),
        }
    return outcomes


def evaluate_duplicate_delivery_cases() -> dict[str, dict[str, Any]]:
    corpus = load_corpus()
    outcomes: dict[str, dict[str, Any]] = {}

    for case in corpus.get("duplicate_delivery", []):
        if case["kind"] == "jira_event":
            connector = JiraConnector(
                config=load_jira_mapping_config("src/sena/examples/integrations/jira_mappings.yaml"),
                verifier=AllowAllJiraWebhookVerifier(),
            )
            payload = _event_payload(case)
            envelope = {
                "headers": case.get("headers") or {},
                "payload": payload,
                "raw_body": json.dumps(payload).encode("utf-8"),
            }
            connector.handle_event(envelope)
            try:
                connector.handle_event(envelope)
            except Exception as exc:  # deterministic integration error contract
                outcomes[case["case_id"]] = {
                    "scenario": case["scenario"],
                    "error": str(exc),
                }
            else:
                outcomes[case["case_id"]] = {
                    "scenario": case["scenario"],
                    "error": "<no-error>",
                }
            continue

        raise ValueError(f"Unsupported duplicate case kind: {case['kind']}")

    return outcomes
