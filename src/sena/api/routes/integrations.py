from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import Response

from sena.api.errors import raise_api_error
from sena.api.runtime import EngineState, parse_default_decision
from sena.api.schemas import WebhookEvaluateRequest
from sena.core.enums import DecisionOutcome
from sena.core.models import EvaluatorConfig
from sena.engine.evaluator import PolicyEvaluator
from sena.integrations.base import DecisionPayload
from sena.integrations.jira import JiraIntegrationError
from sena.integrations.servicenow import ServiceNowIntegrationError
from sena.integrations.slack import SlackIntegrationError
from sena.integrations.webhook import WebhookMappingError


def create_integrations_router(state: EngineState) -> APIRouter:
    router = APIRouter()

    @router.post("/integrations/webhook")
    def integrations_webhook(
        req: WebhookEvaluateRequest,
        request: Request,
        response: Response,
    ) -> dict:
        response.headers["x-sena-surface-stage"] = "experimental"
        if state.webhook_mapper is None:
            raise_api_error("webhook_mapping_not_configured")
        try:
            mapped = state.connector_registry.get("webhook").handle_event(
                {
                    "provider": req.provider,
                    "event_type": req.event_type,
                    "payload": req.payload,
                    "default_request_id": request.state.request_id,
                }
            )
            normalized = mapped["normalized_event"]
            proposal = mapped["action_proposal"]
            evaluator = PolicyEvaluator(
                state.rules,
                policy_bundle=state.metadata,
                config=EvaluatorConfig(
                    default_decision=parse_default_decision(req.default_decision),
                    require_allow_match=req.strict_require_allow,
                    on_escalation=(
                        lambda trace: state.slack_client.send_decision(
                            DecisionPayload(
                                decision_id=trace.decision_id,
                                request_id=trace.request_id,
                                action_type=trace.action_type,
                                matched_rule_ids=[item.rule_id for item in trace.matched_rules],
                                summary=trace.summary,
                            )
                        )
                        if state.slack_client is not None
                        else None
                    ),
                ),
            )
            with state.metrics.evaluation_timer(endpoint="/v1/integrations/webhook"):
                trace = evaluator.evaluate(proposal, req.facts)
            state.metrics.observe_decision_outcome(
                endpoint="/v1/integrations/webhook",
                outcome=trace.outcome.value,
            )
            return {
                "provider": req.provider,
                "event_type": req.event_type,
                "normalized_event": normalized,
                "mapped_action_proposal": {
                    "action_type": proposal.action_type,
                    "request_id": proposal.request_id,
                    "actor_id": proposal.actor_id,
                    "attributes": proposal.attributes,
                },
                "decision": trace.to_dict(),
                "reasoning": trace.reasoning.__dict__ if trace.reasoning else None,
            }
        except WebhookMappingError as exc:
            raise_api_error("webhook_mapping_error", details={"reason": str(exc)})
        except Exception as exc:  # pragma: no cover
            raise_api_error("webhook_evaluation_error", details={"reason": str(exc)})

    @router.post("/integrations/jira/webhook")
    async def integrations_jira_webhook(request: Request) -> dict:
        if state.jira_connector is None:
            raise_api_error("jira_mapping_not_configured")
        raw_body = await request.body()
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            raise_api_error("validation_error", details={"reason": "Malformed JSON body"})

        try:
            mapped = state.connector_registry.get("jira").handle_event(
                {
                    "headers": dict(request.headers.items()),
                    "payload": payload,
                    "raw_body": raw_body,
                }
            )
            normalized = mapped["normalized_event"]
            proposal = mapped["action_proposal"]
            event_route = state.jira_connector.route_for_event_type(normalized["source_event_type"])
            if event_route and event_route.policy_bundle and event_route.policy_bundle != state.metadata.bundle_name:
                raise_api_error(
                    "jira_policy_bundle_not_found",
                    details={
                        "required_bundle": event_route.policy_bundle,
                        "loaded_bundle": state.metadata.bundle_name,
                    },
                )
            evaluator = PolicyEvaluator(
                state.rules,
                policy_bundle=state.metadata,
                config=EvaluatorConfig(default_decision=DecisionOutcome.APPROVED),
            )
            with state.metrics.evaluation_timer(endpoint="/v1/integrations/jira/webhook"):
                trace = evaluator.evaluate(proposal, {})
            outbound = state.jira_connector.send_decision(
                DecisionPayload(
                    decision_id=trace.decision_id,
                    request_id=proposal.request_id,
                    action_type=proposal.action_type,
                    matched_rule_ids=[item.rule_id for item in trace.matched_rules],
                    summary=trace.summary,
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
                "decision": trace.to_dict(),
                "outbound_delivery": outbound,
            }
        except JiraIntegrationError as exc:
            reason = str(exc)
            if "duplicate delivery" in reason:
                return {
                    "status": "duplicate_ignored",
                    "error": {"code": "jira_duplicate_delivery", "message": reason},
                }
            if "unsupported jira event type" in reason:
                raise_api_error("jira_unsupported_event_type", details={"reason": reason})
            if "missing required fields" in reason or "missing actor identity" in reason:
                raise_api_error("jira_missing_required_fields", details={"reason": reason})
            if "signature" in reason:
                raise_api_error("jira_authentication_failed", details={"reason": reason})
            raise_api_error("jira_invalid_mapping", details={"reason": reason})
        except Exception as exc:  # pragma: no cover
            raise_api_error("jira_evaluation_error", details={"reason": str(exc)})

    @router.post("/integrations/servicenow/webhook")
    async def integrations_servicenow_webhook(request: Request, strict_require_allow: bool = False) -> dict:
        if state.servicenow_connector is None:
            raise_api_error("servicenow_mapping_not_configured")
        raw_body = await request.body()
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            raise_api_error("validation_error", details={"reason": "Malformed JSON body"})

        try:
            mapped = state.connector_registry.get("servicenow").handle_event(
                {
                    "headers": dict(request.headers.items()),
                    "payload": payload,
                    "raw_body": raw_body,
                }
            )
            normalized = mapped["normalized_event"]
            proposal = mapped["action_proposal"]
            event_route = state.servicenow_connector.route_for_event_type(normalized["source_event_type"])
            if event_route and event_route.policy_bundle and event_route.policy_bundle != state.metadata.bundle_name:
                raise_api_error(
                    "servicenow_policy_bundle_not_found",
                    details={
                        "required_bundle": event_route.policy_bundle,
                        "loaded_bundle": state.metadata.bundle_name,
                    },
                )

            evaluator = PolicyEvaluator(
                state.rules,
                policy_bundle=state.metadata,
                config=EvaluatorConfig(
                    default_decision=DecisionOutcome.APPROVED,
                    require_allow_match=strict_require_allow,
                ),
            )
            with state.metrics.evaluation_timer(endpoint="/v1/integrations/servicenow/webhook"):
                trace = evaluator.evaluate(proposal, {})
            outbound = state.servicenow_connector.send_decision(
                DecisionPayload(
                    decision_id=trace.decision_id,
                    request_id=proposal.request_id,
                    action_type=proposal.action_type,
                    matched_rule_ids=[item.rule_id for item in trace.matched_rules],
                    summary=trace.summary,
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
                "decision": trace.to_dict(),
                "outbound_delivery": outbound,
            }
        except ServiceNowIntegrationError as exc:
            reason = str(exc)
            if "duplicate delivery" in reason:
                return {
                    "status": "duplicate_ignored",
                    "error": {"code": "servicenow_duplicate_delivery", "message": reason},
                }
            if "unsupported servicenow event type" in reason:
                raise_api_error("servicenow_unsupported_event_type", details={"reason": reason})
            if "missing required fields" in reason or "missing actor identity" in reason:
                raise_api_error("servicenow_missing_required_fields", details={"reason": reason})
            raise_api_error("servicenow_invalid_mapping", details={"reason": reason})
        except Exception as exc:  # pragma: no cover
            raise_api_error("servicenow_evaluation_error", details={"reason": str(exc)})

    @router.post("/integrations/slack/interactions")
    async def slack_interactions(request: Request, response: Response) -> dict:
        response.headers["x-sena-surface-stage"] = "experimental"
        try:
            form_data = await request.form()
            payload_json = form_data.get("payload")
            if not isinstance(payload_json, str):
                raise SlackIntegrationError("Slack interaction payload form field is required")
            interaction = state.connector_registry.get("slack").handle_event(json.loads(payload_json))
            return {
                "status": "ok",
                "decision": interaction["decision"],
                "decision_id": interaction["decision_id"],
                "reviewer": interaction["reviewer"],
            }
        except SlackIntegrationError as exc:
            raise_api_error("slack_interaction_error", details={"reason": str(exc)})
        except Exception as exc:  # pragma: no cover
            raise_api_error("slack_interaction_error", details={"reason": str(exc)})

    return router
