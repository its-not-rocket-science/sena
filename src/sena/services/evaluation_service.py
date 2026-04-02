from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sena.core.enums import ActionOrigin
from sena.core.models import (
    AIActionMetadata,
    ActionProposal,
    AutonomousToolMetadata,
    EvaluatorConfig,
    RiskClassification,
)
from sena.engine.evaluator import PolicyEvaluator
from sena.engine.review_package import build_decision_review_package
from sena.engine.simulation import SimulationScenario, simulate_bundle_impact
from sena.integrations.base import DecisionPayload
from sena.policy.parser import load_policy_bundle
from sena.services.audit_service import AuditService


@dataclass
class EvaluationService:
    state: Any
    audit_service: AuditService

    @staticmethod
    def build_action_proposal(
        *,
        action_type: str,
        request_id: str,
        actor_id: str | None,
        actor_role: str | None,
        attributes: dict[str, Any],
        action_origin: ActionOrigin = ActionOrigin.HUMAN,
        ai_metadata: dict[str, Any] | None = None,
        autonomous_metadata: dict[str, Any] | None = None,
    ) -> ActionProposal:
        normalized_ai_metadata = None
        if ai_metadata is not None:
            risk = ai_metadata.get("risk_classification")
            normalized_ai_metadata = AIActionMetadata(
                originating_system=ai_metadata["originating_system"],
                originating_model=ai_metadata.get("originating_model"),
                prompt_context_ref=ai_metadata.get("prompt_context_ref"),
                confidence=ai_metadata.get("confidence"),
                uncertainty=ai_metadata.get("uncertainty"),
                requested_tool=ai_metadata.get("requested_tool"),
                requested_action=ai_metadata.get("requested_action"),
                evidence_references=list(ai_metadata.get("evidence_references", [])),
                citation_references=list(ai_metadata.get("citation_references", [])),
                human_requester=ai_metadata.get("human_requester"),
                human_owner=ai_metadata.get("human_owner"),
                human_approver=ai_metadata.get("human_approver"),
                risk_classification=RiskClassification(**risk) if risk else None,
            )
        normalized_autonomous_metadata = None
        if autonomous_metadata is not None:
            normalized_autonomous_metadata = AutonomousToolMetadata(**autonomous_metadata)
        return ActionProposal(
            action_type=action_type,
            request_id=request_id,
            actor_id=actor_id,
            actor_role=actor_role,
            attributes=attributes,
            action_origin=action_origin,
            ai_metadata=normalized_ai_metadata,
            autonomous_metadata=normalized_autonomous_metadata,
        )

    def _notify_slack(self, trace: Any) -> None:
        if self.state.slack_client is None:
            return
        self.state.slack_client.send_decision(
            DecisionPayload(
                decision_id=trace.decision_id,
                request_id=trace.request_id,
                action_type=trace.action_type,
                matched_rule_ids=[item.rule_id for item in trace.matched_rules],
                summary=trace.summary,
            )
        )

    def evaluate(
        self,
        *,
        proposal: ActionProposal,
        facts: dict[str, Any],
        endpoint: str,
        default_decision: Any,
        strict_require_allow: bool,
        notify_on_escalation: bool = True,
        append_audit: bool = True,
    ) -> dict[str, Any]:
        evaluator = PolicyEvaluator(
            self.state.rules,
            policy_bundle=self.state.metadata,
            config=EvaluatorConfig(
                default_decision=default_decision,
                require_allow_match=strict_require_allow,
                on_escalation=self._notify_slack if notify_on_escalation else None,
            ),
        )
        with self.state.metrics.evaluation_timer(endpoint=endpoint):
            trace = evaluator.evaluate(proposal, facts)
        self.state.metrics.observe_decision_outcome(endpoint=endpoint, outcome=trace.outcome.value)
        payload = trace.to_dict()
        if append_audit:
            appended = self.audit_service.append_record(payload["audit_record"])
            if appended is not None:
                payload["audit_record"] = appended
        return payload

    def evaluate_review_package(
        self,
        *,
        proposal: ActionProposal,
        facts: dict[str, Any],
        endpoint: str,
        default_decision: Any,
        strict_require_allow: bool,
    ) -> dict[str, Any]:
        evaluator = PolicyEvaluator(
            self.state.rules,
            policy_bundle=self.state.metadata,
            config=EvaluatorConfig(
                default_decision=default_decision,
                require_allow_match=strict_require_allow,
            ),
        )
        with self.state.metrics.evaluation_timer(endpoint=endpoint):
            trace = evaluator.evaluate(proposal, facts)
        self.state.metrics.observe_decision_outcome(endpoint=endpoint, outcome=trace.outcome.value)
        return build_decision_review_package(trace)

    @staticmethod
    def simulate_policy_change(
        *,
        baseline_policy_dir: str,
        candidate_policy_dir: str,
        scenarios: list[dict[str, Any]],
    ) -> dict[str, Any]:
        baseline_rules, baseline_meta = load_policy_bundle(baseline_policy_dir)
        candidate_rules, candidate_meta = load_policy_bundle(candidate_policy_dir)
        scenario_map = {
            item["scenario_id"]: SimulationScenario(
                action_type=item["action_type"],
                request_id=item["request_id"],
                actor_id=item.get("actor_id"),
                attributes=item.get("attributes", {}),
                facts=item["facts"],
                source_system=item.get("source_system", "api"),
                workflow_stage=item.get("workflow_stage"),
                risk_category=item.get("risk_category"),
            )
            for item in scenarios
        }
        return simulate_bundle_impact(
            scenario_map,
            baseline_rules,
            candidate_rules,
            baseline_meta,
            candidate_meta,
        )
