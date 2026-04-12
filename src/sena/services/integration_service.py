from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sena.core.enums import DecisionOutcome
from sena.integrations.base import DecisionPayload


@dataclass
class IntegrationService:
    state: Any
    evaluation_service: Any

    @staticmethod
    def _canonical_payload_hash(canonical_replay_payload: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(
                canonical_replay_payload, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()

    @classmethod
    def _build_normalization_contract(cls, mapped: dict[str, Any]) -> dict[str, Any]:
        canonical_replay_payload = dict(mapped.get("canonical_replay_payload", {}))
        operational_metadata = dict(mapped.get("operational_metadata", {}))
        canonical_replay_payload_hash = cls._canonical_payload_hash(
            canonical_replay_payload
        )
        return {
            "canonical_replay_payload": canonical_replay_payload,
            "operational_metadata": operational_metadata,
            "determinism_scope": "canonical_replay_payload_only",
            "determinism_contract": {
                "scope": "canonical_replay_payload_only",
                "canonical_replay_payload": canonical_replay_payload,
                "operational_metadata": operational_metadata,
                "canonical_replay_payload_hash": canonical_replay_payload_hash,
            },
        }

    @staticmethod
    def _build_mapped_action_proposal(proposal: Any, *, include_actor_role: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "action_type": proposal.action_type,
            "request_id": proposal.request_id,
            "actor_id": proposal.actor_id,
            "attributes": proposal.attributes,
        }
        if include_actor_role:
            payload["actor_role"] = proposal.actor_role
        return payload

    @staticmethod
    def _build_decision_payload(decision: dict[str, Any], proposal: Any) -> DecisionPayload:
        return DecisionPayload(
            decision_id=decision["decision_id"],
            request_id=proposal.request_id,
            action_type=proposal.action_type,
            matched_rule_ids=[item["rule_id"] for item in decision["matched_rules"]],
            summary=decision["summary"],
            merkle_proof=decision.get("decision_hash"),
        )

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
        normalization = {
            "normalized_event": normalized,
            **self._build_normalization_contract(mapped),
        }
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
            "normalization": normalization,
            "normalized_event": normalized,
            "mapped_action_proposal": self._build_mapped_action_proposal(
                proposal, include_actor_role=False
            ),
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
        normalization = {
            "normalized_event": normalized,
            **self._build_normalization_contract(mapped),
        }
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
        reliability = self.state.reliability_service
        decision_payload = self._build_decision_payload(decision, proposal)
        if reliability is None:
            outbound = self.state.jira_connector.send_decision(decision_payload)
        else:
            outbound = reliability.call_dependency(
                dependency_name="jira",
                operation=lambda: self.state.jira_connector.send_decision(
                    decision_payload
                ),
                fallback=lambda reason: self._degraded_outbound_fallback(
                    dependency="jira",
                    reason=reason,
                    decision=decision,
                    request_id=proposal.request_id,
                ),
            )
        return {
            "status": "evaluated",
            "normalization": normalization,
            "normalized_event": normalized,
            "mapped_action_proposal": self._build_mapped_action_proposal(
                proposal, include_actor_role=False
            ),
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
        normalization = {
            "normalized_event": normalized,
            **self._build_normalization_contract(mapped),
        }
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
        reliability = self.state.reliability_service
        decision_payload = self._build_decision_payload(decision, proposal)
        if reliability is None:
            outbound = self.state.servicenow_connector.send_decision(decision_payload)
        else:
            outbound = reliability.call_dependency(
                dependency_name="servicenow",
                operation=lambda: self.state.servicenow_connector.send_decision(
                    decision_payload
                ),
                fallback=lambda reason: self._degraded_outbound_fallback(
                    dependency="servicenow",
                    reason=reason,
                    decision=decision,
                    request_id=proposal.request_id,
                ),
            )
        return {
            "status": "evaluated",
            "normalization": normalization,
            "normalized_event": normalized,
            "mapped_action_proposal": self._build_mapped_action_proposal(
                proposal, include_actor_role=True
            ),
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

    def _degraded_outbound_fallback(
        self,
        *,
        dependency: str,
        reason: str,
        decision: dict[str, Any],
        request_id: str | None,
    ) -> dict[str, Any]:
        self.state.processing_store.enqueue_dead_letter(
            {
                "event_type": "integration_outbound_retry",
                "dependency": dependency,
                "request_id": request_id,
                "decision_id": decision.get("decision_id"),
                "decision_summary": decision.get("summary"),
            },
            f"{dependency} outbound degraded: {reason}",
        )
        return {
            "status": "degraded",
            "fallback_mode": "queue_for_retry",
            "reason": reason,
            "dependency": dependency,
        }
