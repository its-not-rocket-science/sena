from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from sena.api.dependencies import check_idempotency_key, persist_idempotency_response
from sena.api.error_handlers import error_payload
from sena.api.errors import raise_api_error
from sena.api.runtime import EngineState
from sena.api.schemas import WebhookEvaluateRequest
from sena.integrations.jira import JiraIntegrationError
from sena.integrations.servicenow import ServiceNowIntegrationError
from sena.integrations.slack import SlackIntegrationError
from sena.integrations.webhook import WebhookMappingError
from sena.services.integration_service import IntegrationService


def create_integrations_router(state: EngineState) -> APIRouter:
    router = APIRouter(tags=["integrations"], responses={400:{"description":"Bad request"},401:{"description":"Unauthorized"},403:{"description":"Forbidden"},429:{"description":"Rate limited"},500:{"description":"Server error"}})
    integration_service = IntegrationService(
        state=state, evaluation_service=state.processing_service._evaluation
    )

    @router.post("/integrations/webhook", summary="Generic webhook policy evaluation")
    def integrations_webhook(
        req: WebhookEvaluateRequest,
        request: Request,
        response: Response,
        idempotent_response: Response | None = Depends(check_idempotency_key),
    ) -> dict | Response:
        response.headers["x-sena-surface-stage"] = "experimental"
        if idempotent_response is not None:
            return idempotent_response
        if state.webhook_mapper is None:
            raise_api_error("webhook_mapping_not_configured")
        try:
            result = state.processing_service.process_webhook(
                req.model_dump(),
                request_id=request.state.request_id,
            )
            persist_idempotency_response(request, result)
            return result
        except WebhookMappingError as exc:
            state.processing_store.enqueue_dead_letter(
                {
                    "event_type": "webhook",
                    "payload": req.model_dump(),
                    "request_id": request.state.request_id,
                },
                str(exc),
            )
            raise_api_error("webhook_mapping_error", details={"reason": str(exc)})
        except Exception as exc:  # pragma: no cover
            state.processing_store.enqueue_dead_letter(
                {
                    "event_type": "webhook",
                    "payload": req.model_dump(),
                    "request_id": request.state.request_id,
                },
                str(exc),
            )
            raise_api_error("webhook_evaluation_error", details={"reason": str(exc)})

    @router.post("/integrations/jira/webhook", summary="Jira webhook policy evaluation")
    async def integrations_jira_webhook(
        request: Request,
        idempotent_response: Response | None = Depends(check_idempotency_key),
    ) -> dict | Response:
        if idempotent_response is not None:
            return idempotent_response
        if state.jira_connector is None:
            raise_api_error("jira_mapping_not_configured")
        raw_body = await request.body()
        try:
            payload = integration_service.decode_json_body(raw_body)
        except json.JSONDecodeError:
            raise_api_error(
                "validation_error", details={"reason": "Malformed JSON body"}
            )

        try:
            result = state.processing_service.process_jira_webhook(
                headers=dict(request.headers.items()),
                payload=payload,
                raw_body=raw_body,
            )
            persist_idempotency_response(request, result)
            return result
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
                    **error_payload(
                        "jira_duplicate_delivery", reason, request.state.request_id
                    ),
                }
            if "unsupported jira event type" in reason:
                raise_api_error(
                    "jira_unsupported_event_type", details={"reason": reason}
                )
            if (
                "missing required fields" in reason
                or "missing actor identity" in reason
            ):
                raise_api_error(
                    "jira_missing_required_fields", details={"reason": reason}
                )
            if "signature" in reason:
                raise_api_error(
                    "jira_authentication_failed", details={"reason": reason}
                )
            state.processing_store.enqueue_dead_letter(
                {
                    "event_type": "jira_webhook",
                    "payload": payload,
                    "headers": dict(request.headers.items()),
                    "raw_body": raw_body.decode("utf-8"),
                },
                reason,
            )
            raise_api_error("jira_invalid_mapping", details={"reason": reason})
        except Exception as exc:  # pragma: no cover
            state.processing_store.enqueue_dead_letter(
                {
                    "event_type": "jira_webhook",
                    "payload": payload,
                    "headers": dict(request.headers.items()),
                    "raw_body": raw_body.decode("utf-8"),
                },
                str(exc),
            )
            raise_api_error("jira_evaluation_error", details={"reason": str(exc)})

    @router.post("/integrations/servicenow/webhook", summary="ServiceNow webhook policy evaluation")
    async def integrations_servicenow_webhook(
        request: Request,
        strict_require_allow: bool = False,
        idempotent_response: Response | None = Depends(check_idempotency_key),
    ) -> dict | Response:
        if idempotent_response is not None:
            return idempotent_response
        if state.servicenow_connector is None:
            raise_api_error("servicenow_mapping_not_configured")
        raw_body = await request.body()
        try:
            payload = integration_service.decode_json_body(raw_body)
        except json.JSONDecodeError:
            raise_api_error(
                "validation_error", details={"reason": "Malformed JSON body"}
            )

        try:
            result = state.processing_service.process_servicenow_webhook(
                headers=dict(request.headers.items()),
                payload=payload,
                raw_body=raw_body,
                strict_require_allow=strict_require_allow,
            )
            persist_idempotency_response(request, result)
            return result
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
                    **error_payload(
                        "servicenow_duplicate_delivery",
                        reason,
                        request.state.request_id,
                    ),
                }
            if "unsupported servicenow event type" in reason:
                raise_api_error(
                    "servicenow_unsupported_event_type", details={"reason": reason}
                )
            if (
                "missing required fields" in reason
                or "missing actor identity" in reason
            ):
                raise_api_error(
                    "servicenow_missing_required_fields", details={"reason": reason}
                )
            if "signature" in reason:
                raise_api_error(
                    "servicenow_authentication_failed", details={"reason": reason}
                )
            state.processing_store.enqueue_dead_letter(
                {
                    "event_type": "servicenow_webhook",
                    "payload": payload,
                    "headers": dict(request.headers.items()),
                    "raw_body": raw_body.decode("utf-8"),
                    "strict_require_allow": strict_require_allow,
                },
                reason,
            )
            raise_api_error("servicenow_invalid_mapping", details={"reason": reason})
        except Exception as exc:  # pragma: no cover
            state.processing_store.enqueue_dead_letter(
                {
                    "event_type": "servicenow_webhook",
                    "payload": payload,
                    "headers": dict(request.headers.items()),
                    "raw_body": raw_body.decode("utf-8"),
                    "strict_require_allow": strict_require_allow,
                },
                str(exc),
            )
            raise_api_error("servicenow_evaluation_error", details={"reason": str(exc)})

    @router.get("/admin/dlq", summary="List dead-letter queue items")
    def admin_dlq(limit: int = 100) -> dict:
        return {"items": state.processing_store.list_dead_letters(limit=limit)}

    @router.post("/admin/dlq/retry", summary="Retry dead-letter queue items")
    def admin_dlq_retry(ids: list[int] | None = None) -> dict:
        retry_count = state.processing_store.force_retry(ids)
        if state.dlq_worker is not None:
            state.dlq_worker.run_once()
        return {"retried": retry_count}

    @router.post("/integrations/slack/interactions", summary="Handle Slack interactive callbacks")
    async def slack_interactions(request: Request, response: Response) -> dict:
        response.headers["x-sena-surface-stage"] = "experimental"
        try:
            form_data = await request.form()
            payload_json = form_data.get("payload")
            if not isinstance(payload_json, str):
                raise SlackIntegrationError(
                    "Slack interaction payload form field is required"
                )
            return integration_service.handle_slack_interaction(payload_json)
        except SlackIntegrationError as exc:
            raise_api_error("slack_interaction_error", details={"reason": str(exc)})
        except Exception as exc:  # pragma: no cover
            raise_api_error("slack_interaction_error", details={"reason": str(exc)})

    return router
