from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import Response

from sena.api.error_handlers import error_payload
from sena.api.errors import raise_api_error
from sena.api.runtime import EngineState, parse_default_decision
from sena.api.schemas import WebhookEvaluateRequest
from sena.integrations.jira import JiraIntegrationError
from sena.integrations.servicenow import ServiceNowIntegrationError
from sena.integrations.slack import SlackIntegrationError
from sena.integrations.webhook import WebhookMappingError
from sena.services.audit_service import AuditService
from sena.services.evaluation_service import EvaluationService
from sena.services.integration_service import IntegrationService


def create_integrations_router(state: EngineState) -> APIRouter:
    router = APIRouter()
    evaluation_service = EvaluationService(state=state, audit_service=AuditService(state.settings.audit_sink_jsonl))
    integration_service = IntegrationService(state=state, evaluation_service=evaluation_service)

    @router.post("/integrations/webhook")
    def integrations_webhook(req: WebhookEvaluateRequest, request: Request, response: Response) -> dict:
        response.headers["x-sena-surface-stage"] = "experimental"
        if state.webhook_mapper is None:
            raise_api_error("webhook_mapping_not_configured")
        try:
            return integration_service.handle_webhook_event(
                provider=req.provider,
                event_type=req.event_type,
                payload=req.payload,
                facts=req.facts,
                default_decision=parse_default_decision(req.default_decision),
                strict_require_allow=req.strict_require_allow,
                default_request_id=request.state.request_id,
            )
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
            payload = integration_service.decode_json_body(raw_body)
        except json.JSONDecodeError:
            raise_api_error("validation_error", details={"reason": "Malformed JSON body"})

        try:
            return integration_service.handle_jira_event(
                headers=dict(request.headers.items()),
                payload=payload,
                raw_body=raw_body,
            )
        except LookupError as exc:
            raise_api_error(
                "jira_policy_bundle_not_found",
                details={
                    "required_bundle": str(exc),
                    "loaded_bundle": state.metadata.bundle_name,
                },
            )
        except JiraIntegrationError as exc:
            reason = str(exc)
            if "duplicate delivery" in reason:
                return {
                    "status": "duplicate_ignored",
                    **error_payload("jira_duplicate_delivery", reason, request.state.request_id),
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
            payload = integration_service.decode_json_body(raw_body)
        except json.JSONDecodeError:
            raise_api_error("validation_error", details={"reason": "Malformed JSON body"})

        try:
            return integration_service.handle_servicenow_event(
                headers=dict(request.headers.items()),
                payload=payload,
                raw_body=raw_body,
                strict_require_allow=strict_require_allow,
            )
        except LookupError as exc:
            raise_api_error(
                "servicenow_policy_bundle_not_found",
                details={
                    "required_bundle": str(exc),
                    "loaded_bundle": state.metadata.bundle_name,
                },
            )
        except ServiceNowIntegrationError as exc:
            reason = str(exc)
            if "duplicate delivery" in reason:
                return {
                    "status": "duplicate_ignored",
                    **error_payload("servicenow_duplicate_delivery", reason, request.state.request_id),
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
            return integration_service.handle_slack_interaction(payload_json)
        except SlackIntegrationError as exc:
            raise_api_error("slack_interaction_error", details={"reason": str(exc)})
        except Exception as exc:  # pragma: no cover
            raise_api_error("slack_interaction_error", details={"reason": str(exc)})

    return router
