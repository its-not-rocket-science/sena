from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sena.core.models import ActionProposal, EvaluatorConfig
from sena.engine.evaluator import PolicyEvaluator
from sena.engine.review_package import build_decision_review_package
from sena.integrations.base import DecisionPayload
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
    ) -> ActionProposal:
        return ActionProposal(
            action_type=action_type,
            request_id=request_id,
            actor_id=actor_id,
            actor_role=actor_role,
            attributes=attributes,
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
