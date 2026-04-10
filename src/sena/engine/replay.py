from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sena import __version__ as SENA_VERSION
from sena.core.enums import ActionOrigin
from sena.core.models import (
    AIActionMetadata,
    ActionProposal,
    AutonomousToolMetadata,
    EvaluationTrace,
    EvaluatorConfig,
    PolicyBundleMetadata,
    PolicyRule,
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
from sena.integrations.webhook import WebhookPayloadMapper, load_webhook_mapping_config


_CONTEXT_KEYS = {
    "action_type",
    "request_id",
    "actor_id",
    "actor_role",
    "action_origin",
    "ai_metadata",
    "autonomous_metadata",
}

_VOLATILE_TRACE_FIELDS = {
    "decision_id",
    "decision_timestamp",
    "operational_metadata",
}


@dataclass(frozen=True)
class ReplayCase:
    case_id: str
    proposal: ActionProposal
    facts: dict[str, Any]
    source_system: str
    workflow_stage: str
    risk_category: str


@dataclass(frozen=True)
class ReplayEvaluation:
    case_id: str
    outcome: str
    matched_controls: list[str]
    missing_evidence: list[str]
    escalation: bool


@dataclass(frozen=True)
class ReplayDriftChange:
    case_id: str
    before_outcome: str
    after_outcome: str
    outcome_changed: bool
    before_matched_controls: list[str]
    after_matched_controls: list[str]
    matched_controls_changed: bool
    before_missing_evidence: list[str]
    after_missing_evidence: list[str]
    missing_evidence_changed: bool
    source_system: str
    workflow_stage: str
    risk_category: str


class ReplayInputError(ValueError):
    """Raised when replay fixtures are malformed."""


def export_canonical_replay_artifact(trace: EvaluationTrace) -> dict[str, Any]:
    canonical_payload = dict(trace.canonical_replay_payload or {})
    if not canonical_payload:
        raise ReplayInputError("trace does not contain canonical_replay_payload")
    if "decision_hash" not in canonical_payload:
        raise ReplayInputError(
            "canonical_replay_payload must include decision_hash for verification"
        )
    if "input_fingerprint" not in canonical_payload:
        raise ReplayInputError(
            "canonical_replay_payload must include input_fingerprint for verification"
        )

    normalized_trace = trace.to_dict()
    for field in _VOLATILE_TRACE_FIELDS:
        normalized_trace.pop(field, None)
    if isinstance(normalized_trace.get("audit_record"), dict):
        normalized_trace["audit_record"].pop("decision_id", None)
        normalized_trace["audit_record"].pop("timestamp", None)
        normalized_trace["audit_record"].pop("write_timestamp", None)
        normalized_trace["audit_record"].pop("chain_hash", None)
        normalized_trace["audit_record"].pop("previous_chain_hash", None)
        normalized_trace["audit_record"].pop("operational_metadata", None)
    normalized_trace.pop("canonical_replay_payload", None)

    payload_hash = hashlib.sha256(
        json.dumps(canonical_payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return {
        "artifact_schema": "sena.canonical_replay_artifact.v1",
        "determinism_scope": "canonical_replay_payload_only",
        "canonical_replay_payload": canonical_payload,
        "canonical_replay_payload_hash": payload_hash,
        "provenance": {
            "evaluator_version": SENA_VERSION,
            "policy_bundle": canonical_payload.get("policy_bundle"),
            "decision_hash": canonical_payload["decision_hash"],
            "input_fingerprint": canonical_payload["input_fingerprint"],
        },
        "excluded_volatile_fields": sorted(_VOLATILE_TRACE_FIELDS),
        "operational_response_payload": normalized_trace,
    }


def _normalize_action_origin(raw: str | None) -> ActionOrigin:
    if raw == ActionOrigin.AI_SUGGESTED.value:
        return ActionOrigin.AI_SUGGESTED
    if raw == ActionOrigin.AUTONOMOUS_TOOL.value:
        return ActionOrigin.AUTONOMOUS_TOOL
    return ActionOrigin.HUMAN


def _proposal_from_payload(payload: dict[str, Any]) -> ActionProposal:
    ai_payload = payload.get("ai_metadata")
    autonomous_payload = payload.get("autonomous_metadata")
    ai_metadata = (
        AIActionMetadata(**ai_payload) if isinstance(ai_payload, dict) else None
    )
    autonomous_metadata = (
        AutonomousToolMetadata(**autonomous_payload)
        if isinstance(autonomous_payload, dict)
        else None
    )
    return ActionProposal(
        action_type=str(payload["action_type"]),
        request_id=payload.get("request_id"),
        actor_id=payload.get("actor_id"),
        actor_role=payload.get("actor_role"),
        attributes=dict(payload.get("attributes") or {}),
        action_origin=_normalize_action_origin(payload.get("action_origin")),
        ai_metadata=ai_metadata,
        autonomous_metadata=autonomous_metadata,
    )


def _proposal_from_trace_payload(
    payload: dict[str, Any],
) -> tuple[ActionProposal, dict[str, Any]]:
    context = payload.get("context") or {}
    if not isinstance(context, dict):
        raise ReplayInputError("trace payload requires object 'context'")

    attributes = {
        key: value for key, value in context.items() if key not in _CONTEXT_KEYS
    }
    proposal = ActionProposal(
        action_type=str(payload.get("action_type") or context.get("action_type") or ""),
        request_id=payload.get("request_id") or context.get("request_id"),
        actor_id=context.get("actor_id"),
        actor_role=context.get("actor_role"),
        attributes=attributes,
        action_origin=_normalize_action_origin(
            str(context.get("action_origin") or "human")
        ),
        ai_metadata=AIActionMetadata(**context["ai_metadata"])
        if isinstance(context.get("ai_metadata"), dict)
        else None,
        autonomous_metadata=(
            AutonomousToolMetadata(**context["autonomous_metadata"])
            if isinstance(context.get("autonomous_metadata"), dict)
            else None
        ),
    )
    if not proposal.action_type:
        raise ReplayInputError("trace payload must include action_type")
    return proposal, {}


def _proposal_from_mapping_case(
    case: dict[str, Any], mapping_mode: str, mapping_config_path: str
) -> tuple[ActionProposal, dict[str, Any]]:
    event = case.get("event")
    if not isinstance(event, dict):
        raise ReplayInputError("mapping case requires object 'event'")
    if mapping_mode == "jira":
        connector = JiraConnector(
            config=load_jira_mapping_config(mapping_config_path),
            verifier=AllowAllJiraWebhookVerifier(),
        )
        normalized = connector.handle_event(
            {
                "headers": event.get("headers") or {},
                "payload": event.get("payload") or {},
                "raw_body": (event.get("raw_body") or "").encode("utf-8"),
            }
        )
    elif mapping_mode == "servicenow":
        connector = ServiceNowConnector(
            config=load_servicenow_mapping_config(mapping_config_path)
        )
        normalized = connector.handle_event(
            {
                "headers": event.get("headers") or {},
                "payload": event.get("payload") or {},
                "raw_body": b"",
            }
        )
    elif mapping_mode == "webhook":
        connector = WebhookPayloadMapper(
            config=load_webhook_mapping_config(mapping_config_path)
        )
        normalized = connector.handle_event(
            {
                "provider": event.get("provider"),
                "event_type": event.get("event_type"),
                "payload": event.get("payload") or {},
                "default_request_id": event.get("default_request_id")
                or case.get("case_id", "replay"),
            }
        )
    else:
        raise ReplayInputError(f"unsupported mapping mode '{mapping_mode}'")

    proposal_payload = normalized["action_proposal"]
    if isinstance(proposal_payload, ActionProposal):
        proposal = proposal_payload
    elif isinstance(proposal_payload, dict):
        proposal_payload["action_origin"] = "autonomous_tool"
        proposal = _proposal_from_payload(proposal_payload)
    else:
        raise ReplayInputError(
            "connector mapping output must contain an ActionProposal"
        )
    return proposal, dict(case.get("facts") or {})


def load_replay_cases(
    payload: dict[str, Any],
    *,
    mapping_mode: str | None = None,
    mapping_config_path: str | None = None,
) -> list[ReplayCase]:
    cases_payload = payload.get("cases")
    if not isinstance(cases_payload, list) or not cases_payload:
        raise ReplayInputError("replay payload requires non-empty 'cases' list")

    parsed: list[ReplayCase] = []
    for idx, case in enumerate(cases_payload, start=1):
        if not isinstance(case, dict):
            raise ReplayInputError(f"replay case index {idx} must be an object")
        case_id = str(case.get("case_id") or f"case_{idx}")

        if mapping_mode:
            if not mapping_config_path:
                raise ReplayInputError(
                    "mapping_config_path is required when mapping_mode is used"
                )
            proposal, facts = _proposal_from_mapping_case(
                case, mapping_mode, mapping_config_path
            )
        elif isinstance(case.get("proposal"), dict):
            proposal = _proposal_from_payload(case["proposal"])
            facts = dict(case.get("facts") or {})
        elif isinstance(case.get("trace"), dict):
            proposal, facts = _proposal_from_trace_payload(case["trace"])
        else:
            raise ReplayInputError(
                f"replay case '{case_id}' must include one of: proposal, trace, or event (with mapping_mode)"
            )

        source_system = str(
            case.get("source_system")
            or proposal.attributes.get("source_system")
            or "unknown"
        )
        workflow_stage = str(
            case.get("workflow_stage")
            or proposal.attributes.get("workflow_stage")
            or "unknown"
        )
        risk_category = str(
            case.get("risk_category")
            or proposal.attributes.get("risk_category")
            or "general"
        )
        parsed.append(
            ReplayCase(
                case_id=case_id,
                proposal=proposal,
                facts=facts,
                source_system=source_system,
                workflow_stage=workflow_stage,
                risk_category=risk_category,
            )
        )
    return parsed


def evaluate_replay_cases(
    *,
    cases: list[ReplayCase],
    rules: list[PolicyRule],
    metadata: PolicyBundleMetadata,
    config: EvaluatorConfig | None = None,
) -> dict[str, ReplayEvaluation]:
    evaluator = PolicyEvaluator(
        rules, policy_bundle=metadata, config=config or EvaluatorConfig()
    )
    results: dict[str, ReplayEvaluation] = {}
    for case in cases:
        trace = evaluator.evaluate(case.proposal, case.facts)
        missing_evidence = sorted(
            {
                evidence
                for rule in trace.matched_rules
                for evidence in rule.missing_evidence
            }
        )
        results[case.case_id] = ReplayEvaluation(
            case_id=case.case_id,
            outcome=trace.outcome.value,
            matched_controls=sorted(rule.rule_id for rule in trace.matched_rules),
            missing_evidence=missing_evidence,
            escalation=trace.outcome.value == "ESCALATE_FOR_HUMAN_REVIEW",
        )
    return results


def build_drift_report(
    *,
    cases: list[ReplayCase],
    baseline: dict[str, ReplayEvaluation],
    candidate: dict[str, ReplayEvaluation],
    baseline_label: str,
    candidate_label: str,
) -> dict[str, Any]:
    changes: list[ReplayDriftChange] = []
    for case in cases:
        before = baseline[case.case_id]
        after = candidate[case.case_id]
        changes.append(
            ReplayDriftChange(
                case_id=case.case_id,
                before_outcome=before.outcome,
                after_outcome=after.outcome,
                outcome_changed=before.outcome != after.outcome,
                before_matched_controls=before.matched_controls,
                after_matched_controls=after.matched_controls,
                matched_controls_changed=before.matched_controls
                != after.matched_controls,
                before_missing_evidence=before.missing_evidence,
                after_missing_evidence=after.missing_evidence,
                missing_evidence_changed=before.missing_evidence
                != after.missing_evidence,
                source_system=case.source_system,
                workflow_stage=case.workflow_stage,
                risk_category=case.risk_category,
            )
        )

    changed_outcomes = [change for change in changes if change.outcome_changed]
    changed_controls = [change for change in changes if change.matched_controls_changed]
    changed_evidence = [change for change in changes if change.missing_evidence_changed]

    total = len(changes)
    baseline_escalations = sum(1 for item in baseline.values() if item.escalation)
    candidate_escalations = sum(1 for item in candidate.values() if item.escalation)
    baseline_rate = 0.0 if total == 0 else baseline_escalations / total
    candidate_rate = 0.0 if total == 0 else candidate_escalations / total

    return {
        "replay_type": "sena.ai_workflow_drift",
        "baseline_label": baseline_label,
        "candidate_label": candidate_label,
        "total_cases": total,
        "changed_outcomes": len(changed_outcomes),
        "changed_matched_controls": len(changed_controls),
        "changed_missing_evidence": len(changed_evidence),
        "escalation_rates": {
            "before": {
                "count": baseline_escalations,
                "rate": baseline_rate,
            },
            "after": {
                "count": candidate_escalations,
                "rate": candidate_rate,
            },
            "delta": candidate_rate - baseline_rate,
        },
        "changes": [item.__dict__ for item in changes],
    }
