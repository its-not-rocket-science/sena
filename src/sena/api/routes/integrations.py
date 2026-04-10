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
from sena.services.reliability_service import QueueOverflowError


def create_integrations_router(state: EngineState) -> APIRouter:
    router = APIRouter(tags=["integrations"], responses={400:{"description":"Bad request"},401:{"description":"Unauthorized"},403:{"description":"Forbidden"},429:{"description":"Rate limited"},500:{"description":"Server error"}})
    integration_service = IntegrationService(
        state=state, evaluation_service=state.processing_service._evaluation
    )

    def _supported_connector(name: str):
        if name == "jira":
            return state.jira_connector
        if name == "servicenow":
            return state.servicenow_connector
        raise_api_error(
            "validation_error",
            details={"reason": "connector must be one of: jira, servicenow"},
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
            result = state.processing_service.enqueue_and_process(
                {
                    "event_type": "webhook",
                    "payload": req.model_dump(),
                    "request_id": request.state.request_id,
                }
            )
            persist_idempotency_response(request, result)
            return result
        except QueueOverflowError as exc:
            raise_api_error("rate_limited", details={"reason": str(exc)})
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
            result = state.processing_service.enqueue_and_process(
                {
                    "event_type": "jira_webhook",
                    "headers": dict(request.headers.items()),
                    "payload": payload,
                    "raw_body": raw_body.decode("utf-8"),
                }
            )
            persist_idempotency_response(request, result)
            return result
        except QueueOverflowError as exc:
            raise_api_error("rate_limited", details={"reason": str(exc)})
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
                signature_error = (
                    "missing_signature" if "missing webhook signature" in reason else "invalid_signature"
                )
                raise_api_error(
                    "jira_authentication_failed",
                    details={
                        "reason": reason,
                        "signature_error": signature_error,
                    },
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
            result = state.processing_service.enqueue_and_process(
                {
                    "event_type": "servicenow_webhook",
                    "headers": dict(request.headers.items()),
                    "payload": payload,
                    "raw_body": raw_body.decode("utf-8"),
                    "strict_require_allow": strict_require_allow,
                }
            )
            persist_idempotency_response(request, result)
            return result
        except QueueOverflowError as exc:
            raise_api_error("rate_limited", details={"reason": str(exc)})
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
                signature_error = (
                    "missing_signature" if "missing webhook signature" in reason else "invalid_signature"
                )
                raise_api_error(
                    "servicenow_authentication_failed",
                    details={
                        "reason": reason,
                        "signature_error": signature_error,
                    },
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

    @router.get("/admin/data-access", summary="List governed data access events")
    def admin_data_access(limit: int = 100) -> dict:
        return {"items": state.processing_store.list_data_access_events(limit=limit)}

    @router.get(
        "/integrations/{connector}/admin/outbound/completions",
        summary="List outbound delivery completion records",
    )
    def admin_outbound_completions(connector: str, limit: int = 100) -> dict:
        selected = _supported_connector(connector)
        if selected is None:
            raise_api_error(
                "validation_error",
                details={"reason": f"{connector} connector is not configured"},
            )
        return {"items": selected.outbound_completion_records(limit=limit)}

    @router.get(
        "/integrations/{connector}/admin/outbound/dead-letter",
        summary="List outbound delivery dead-letter records",
    )
    def admin_outbound_dead_letter(connector: str, limit: int = 100) -> dict:
        selected = _supported_connector(connector)
        if selected is None:
            raise_api_error(
                "validation_error",
                details={"reason": f"{connector} connector is not configured"},
            )
        return {"items": selected.outbound_dead_letter_records(limit=limit)}

    @router.post(
        "/integrations/{connector}/admin/outbound/dead-letter/replay",
        summary="Replay outbound dead-letter records",
    )
    def admin_outbound_dead_letter_replay(connector: str, ids: list[int]) -> dict:
        selected = _supported_connector(connector)
        if selected is None:
            raise_api_error(
                "validation_error",
                details={"reason": f"{connector} connector is not configured"},
            )
        items: list[dict] = []
        for dead_letter_id in ids:
            items.append(selected.replay_dead_letter(int(dead_letter_id)))
        return {"items": items}

    @router.post(
        "/integrations/{connector}/admin/outbound/dead-letter/manual-redrive",
        summary="Manually mark outbound dead-letter records as redriven",
    )
    def admin_outbound_dead_letter_manual_redrive(
        connector: str, ids: list[int], note: str = "manually redriven"
    ) -> dict:
        selected = _supported_connector(connector)
        if selected is None:
            raise_api_error(
                "validation_error",
                details={"reason": f"{connector} connector is not configured"},
            )
        items: list[dict] = []
        for dead_letter_id in ids:
            items.append(
                selected.manual_redrive_dead_letter(int(dead_letter_id), note=note)
            )
        return {"items": items, "note": note}

    @router.get(
        "/integrations/{connector}/admin/outbound/duplicates/summary",
        summary="Summarize duplicate suppression counts",
    )
    def admin_outbound_duplicate_summary(connector: str) -> dict:
        selected = _supported_connector(connector)
        if selected is None:
            raise_api_error(
                "validation_error",
                details={"reason": f"{connector} connector is not configured"},
            )
        return selected.outbound_duplicate_suppression_summary()

    @router.get("/admin/slo", summary="Production SLO targets")
    def admin_slo() -> dict:
        reliability = state.reliability_service
        if reliability is None:
            return {"slo_definitions": []}
        return reliability.slo_payload()

    @router.get("/admin/data/payloads", summary="List governed payloads by tenant and region")
    def admin_data_payloads(
        tenant_id: str,
        region: str,
        include_expired: bool = False,
    ) -> dict:
        items = state.processing_store.list_governed_payloads(
            tenant_id=tenant_id,
            region=region,
            include_expired=include_expired,
        )
        return {"items": items}

    @router.post("/admin/data/payloads/{payload_id}/hold", summary="Apply legal hold to governed payload")
    def admin_data_payload_hold(payload_id: int, reason: str = "legal_hold") -> dict:
        updated = state.processing_store.apply_governed_payload_legal_hold(
            payload_id,
            reason=reason,
        )
        return {"payload_id": payload_id, "held": updated}

    @router.post("/admin/audit/config", summary="Update audit verification controls")
    def admin_audit_config(payload: dict[str, bool], request: Request) -> dict:
        role = getattr(request.state, "api_role", "")
        if role in {"policy_author", "deployer"}:
            raise_api_error(
                "forbidden",
                details={
                    "reason": "separation_of_duties: only reviewer or auditor may change audit configuration"
                },
            )
        if role and not request.headers.get("x-step-up-auth"):
            raise_api_error(
                "forbidden",
                details={
                    "reason": "step_up_auth_required",
                    "required_header": "x-step-up-auth",
                },
            )
        if role and not request.headers.get("x-secondary-approver-id"):
            raise_api_error(
                "forbidden",
                details={
                    "reason": "secondary_approval_required",
                    "required_header": "x-secondary-approver-id",
                },
            )
        return {
            "status": "accepted",
            "requested_changes": payload,
            "requires_restart": True,
        }

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
