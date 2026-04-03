from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sena.core.enums import DecisionOutcome
from sena.integrations.base import DecisionPayload


@dataclass
class IntegrationService:
    state: Any
    evaluation_service: Any

    def handle_webhook_event(
        self,
        *,
        provider: str,
        event_type: str,
        payload: dict[str, Any],
        facts: dict[str, Any],
        default_decision: Any,
        strict_require_allow: bool,
        default_request_id: str,
    ) -> dict[str, Any]:
        mapped = self.state.connector_registry.get("webhook").handle_event(
            {
                "provider": provider,
                "event_type": event_type,
                "payload": payload,
                "default_request_id": default_request_id,
            }
        )
        normalized = mapped["normalized_event"]
        proposal = mapped["action_proposal"]
        decision = self.evaluation_service.evaluate(
            proposal=proposal,
            facts=facts,
            endpoint="/v1/integrations/webhook",
            default_decision=default_decision,
            strict_require_allow=strict_require_allow,
            notify_on_escalation=True,
            append_audit=False,
        )
        return {
            "provider": provider,
            "event_type": event_type,
            "normalized_event": normalized,
            "mapped_action_proposal": {
                "action_type": proposal.action_type,
                "request_id": proposal.request_id,
                "actor_id": proposal.actor_id,
                "attributes": proposal.attributes,
            },
            "decision": decision,
            "reasoning": decision.get("reasoning"),
        }

    def decode_json_body(self, raw_body: bytes) -> dict[str, Any]:
        return json.loads(raw_body.decode("utf-8"))

    def handle_jira_event(
        self, *, headers: dict[str, str], payload: dict[str, Any], raw_body: bytes
    ) -> dict[str, Any]:
        mapped = self.state.connector_registry.get("jira").handle_event(
            {
                "headers": headers,
                "payload": payload,
                "raw_body": raw_body,
            }
        )
        normalized = mapped["normalized_event"]
        proposal = mapped["action_proposal"]
        event_route = self.state.jira_connector.route_for_event_type(
            normalized["source_event_type"]
        )
        if (
            event_route
            and event_route.policy_bundle
            and event_route.policy_bundle != self.state.metadata.bundle_name
        ):
            raise LookupError(event_route.policy_bundle)
        decision = self.evaluation_service.evaluate(
            proposal=proposal,
            facts={},
            endpoint="/v1/integrations/jira/webhook",
            default_decision=DecisionOutcome.APPROVED,
            strict_require_allow=False,
            notify_on_escalation=False,
            append_audit=False,
        )
        outbound = self.state.jira_connector.send_decision(
            DecisionPayload(
                decision_id=decision["decision_id"],
                request_id=proposal.request_id,
                action_type=proposal.action_type,
                matched_rule_ids=[
                    item["rule_id"] for item in decision["matched_rules"]
                ],
                summary=decision["summary"],
                merkle_proof=decision.get("decision_hash"),
            )
        )
        return {
            "status": "evaluated",
            "normalized_event": normalized,
            "mapped_action_proposal": {
                "action_type": proposal.action_type,
                "request_id": proposal.request_id,
                "actor_id": proposal.actor_id,
                "attributes": proposal.attributes,
            },
            "decision": decision,
            "outbound_delivery": outbound,
        }

    def handle_servicenow_event(
        self,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        raw_body: bytes,
        strict_require_allow: bool,
    ) -> dict[str, Any]:
        mapped = self.state.connector_registry.get("servicenow").handle_event(
            {
                "headers": headers,
                "payload": payload,
                "raw_body": raw_body,
            }
        )
        normalized = mapped["normalized_event"]
        proposal = mapped["action_proposal"]
        event_route = self.state.servicenow_connector.route_for_event_type(
            normalized["source_event_type"]
        )
        if (
            event_route
            and event_route.policy_bundle
            and event_route.policy_bundle != self.state.metadata.bundle_name
        ):
            raise LookupError(event_route.policy_bundle)
        decision = self.evaluation_service.evaluate(
            proposal=proposal,
            facts={},
            endpoint="/v1/integrations/servicenow/webhook",
            default_decision=DecisionOutcome.APPROVED,
            strict_require_allow=strict_require_allow,
            notify_on_escalation=False,
            append_audit=False,
        )
        outbound = self.state.servicenow_connector.send_decision(
            DecisionPayload(
                decision_id=decision["decision_id"],
                request_id=proposal.request_id,
                action_type=proposal.action_type,
                matched_rule_ids=[
                    item["rule_id"] for item in decision["matched_rules"]
                ],
                summary=decision["summary"],
                merkle_proof=decision.get("decision_hash"),
            )
        )
        return {
            "status": "evaluated",
            "normalized_event": normalized,
            "mapped_action_proposal": {
                "action_type": proposal.action_type,
                "request_id": proposal.request_id,
                "actor_id": proposal.actor_id,
                "actor_role": proposal.actor_role,
                "attributes": proposal.attributes,
            },
            "decision": decision,
            "outbound_delivery": outbound,
        }

    def handle_slack_interaction(self, payload_json: str) -> dict[str, Any]:
        interaction = self.state.connector_registry.get("slack").handle_event(
            json.loads(payload_json)
        )
        return {
            "status": "ok",
            "decision": interaction["decision"],
            "decision_id": interaction["decision_id"],
            "reviewer": interaction["reviewer"],
        }
