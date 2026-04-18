from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response

from sena.api.auth import evaluate_sensitive_operation
from sena.api.dependencies import (
    idempotency_key_lock,
    idempotency_request_fingerprint,
    persist_idempotency_response,
)
from sena.api.error_handlers import error_payload
from sena.api.errors import raise_api_error
from sena.api.logging import get_logger
from sena.api.runtime import EngineState
from sena.api.schemas import WebhookEvaluateRequest
from sena.integrations.jira import JiraIntegrationError
from sena.integrations.servicenow import ServiceNowIntegrationError
from sena.integrations.slack import SlackIntegrationError
from sena.integrations.webhook import WebhookMappingError
from sena.services.integration_service import IntegrationService
from sena.services.reliability_service import QueueOverflowError

logger = get_logger(__name__)
_DEFAULT_LIST_LIMIT = 100
_MAX_LIST_LIMIT = 1000
_MAX_NOTE_LENGTH = 1024
_SENSITIVE_HEADER_NAMES = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-sena-signature",
    "x-hub-signature-256",
    "x-servicenow-signature",
}


def create_integrations_router(state: EngineState) -> APIRouter:
    router = APIRouter(tags=["integrations"], responses={400:{"description":"Bad request"},401:{"description":"Unauthorized"},403:{"description":"Forbidden"},429:{"description":"Rate limited"},500:{"description":"Server error"}})
    integration_service = IntegrationService(
        state=state,
        evaluation_service=state.processing_service.evaluation_service,
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

    def _configured_connector(name: str):
        connector = _supported_connector(name)
        if connector is not None:
            return connector
        if name == "jira":
            raise_api_error("jira_mapping_not_configured")
        if name == "servicenow":
            raise_api_error("servicenow_mapping_not_configured")
        raise_api_error(
            "validation_error",
            details={"reason": "connector must be one of: jira, servicenow"},
        )

    def _ok(payload: dict) -> dict:
        if "status" not in payload:
            payload["status"] = "ok"
        return payload

    def _list_response(items: list[dict], **extras: object) -> dict:
        return _ok(
            {
                "count": len(items),
                "items": items,
                **extras,
            }
        )

    def _bounded_limit(limit: int) -> tuple[int, int]:
        requested = int(limit)
        if requested < 1:
            raise_api_error(
                "validation_error",
                details={"reason": "limit must be >= 1"},
            )
        return requested, min(requested, _MAX_LIST_LIMIT)

    def _normalize_note(note: str) -> str:
        normalized = str(note).strip()
        if not normalized:
            raise_api_error(
                "validation_error",
                details={"reason": "note must not be empty"},
            )
        if len(normalized) > _MAX_NOTE_LENGTH:
            raise_api_error(
                "validation_error",
                details={"reason": f"note exceeds {_MAX_NOTE_LENGTH} characters"},
            )
        if any(ord(ch) < 32 for ch in normalized):
            raise_api_error(
                "validation_error",
                details={"reason": "note contains control characters"},
            )
        return normalized

    def _bulk_dead_letter_action(
        *,
        connector: str,
        ids: list[int],
        action_name: str,
        action_fn: Callable[[Any, int], dict[str, Any]],
    ) -> dict:
        selected = _configured_connector(connector)
        items: list[dict[str, Any]] = []
        succeeded = 0
        not_found = 0
        failed = 0
        for dead_letter_id in ids:
            current_id = int(dead_letter_id)
            try:
                result = action_fn(selected, current_id)
                result.setdefault("dead_letter_id", current_id)
                items.append(result)
                succeeded += 1
            except (JiraIntegrationError, ServiceNowIntegrationError) as exc:
                reason = str(exc)
                if "dead-letter record not found" in reason:
                    not_found += 1
                    items.append(
                        {
                            "dead_letter_id": current_id,
                            "status": "not_found",
                            "reason": reason,
                        }
                    )
                    continue
                failed += 1
                items.append(
                    {
                        "dead_letter_id": current_id,
                        "status": "failed",
                        "reason": reason,
                    }
                )
        logger.info(
            "connector_outbound_dead_letter_admin_action_requested",
            connector=connector,
            action=action_name,
            requested_ids=len(ids),
            succeeded=succeeded,
            not_found=not_found,
            failed=failed,
        )
        return _list_response(
            items,
            requested=len(ids),
            succeeded=succeeded,
            not_found=not_found,
            failed=failed,
        )

    def _redacted_headers(headers: dict[str, str]) -> dict[str, str]:
        redacted: dict[str, str] = {}
        for key, value in headers.items():
            normalized = str(key).lower()
            if normalized in _SENSITIVE_HEADER_NAMES:
                redacted[key] = "<redacted>"
                continue
            rendered = str(value)
            redacted[key] = rendered if len(rendered) <= 256 else f"{rendered[:256]}...(truncated)"
        return redacted

    def _integration_dead_letter_event(
        *,
        event_type: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        raw_body: bytes,
        strict_require_allow: bool | None = None,
    ) -> dict[str, Any]:
        event: dict[str, Any] = {
            "event_type": event_type,
            "payload": payload,
            "headers": _redacted_headers(headers),
            "raw_body_sha256": hashlib.sha256(raw_body).hexdigest(),
            "raw_body_bytes": len(raw_body),
        }
        if strict_require_allow is not None:
            event["strict_require_allow"] = strict_require_allow
        return event

    def _connector_error_details(
        *,
        connector: str,
        stage: str,
        reason: str,
        **extra: Any,
    ) -> dict[str, Any]:
        details: dict[str, Any] = {
            "connector": connector,
            "stage": stage,
            "reason": reason,
        }
        details.update(extra)
        return details

    @router.post("/integrations/webhook", summary="Generic webhook policy evaluation")
    def integrations_webhook(
        req: WebhookEvaluateRequest,
        request: Request,
        response: Response,
    ) -> dict | Response:
        response.headers["x-sena-surface-stage"] = "experimental"
        if state.webhook_mapper is None:
            raise_api_error("webhook_mapping_not_configured")
        key = request.headers.get("Idempotency-Key")
        request_payload = req.model_dump()
        with idempotency_key_lock(key):
            if key:
                existing = state.processing_store.get_idempotency_entry(key)
                if existing is not None:
                    cached_response, fingerprint = existing
                    incoming_fingerprint = idempotency_request_fingerprint(
                        request, request_payload
                    )
                    if (
                        fingerprint is not None
                        and incoming_fingerprint is not None
                        and fingerprint != incoming_fingerprint
                    ):
                        raise_api_error(
                            "validation_error",
                            message="Idempotency-Key has already been used with a different payload.",
                            details={"reason": "idempotency_key_conflict"},
                            status_code=409,
                        )
                    return Response(
                        content=cached_response,
                        media_type="application/json",
                        status_code=200,
                    )
            try:
                state.metrics.observe_connector_inbound_event_received(
                    connector="webhook",
                    event_type=req.event_type,
                )
                logger.info(
                    "connector_inbound_event_received",
                    connector="webhook",
                    event_type=req.event_type,
                    provider=req.provider,
                )
                result = state.processing_service.enqueue_and_process(
                    {
                        "event_type": "webhook",
                        "payload": request_payload,
                        "request_id": request.state.request_id,
                    }
                )
                persist_idempotency_response(
                    request, result, request_payload=request_payload
                )
                return _ok(result)
            except QueueOverflowError as exc:
                raise_api_error("rate_limited", details={"reason": str(exc)})
            except WebhookMappingError as exc:
                state.processing_store.enqueue_dead_letter(
                    {
                        "event_type": "webhook",
                        "payload": request_payload,
                        "request_id": request.state.request_id,
                    },
                    str(exc),
                )
                raise_api_error("webhook_mapping_error", details={"reason": str(exc)})
            except Exception as exc:  # pragma: no cover
                state.processing_store.enqueue_dead_letter(
                    {
                        "event_type": "webhook",
                        "payload": request_payload,
                        "request_id": request.state.request_id,
                    },
                    str(exc),
                )
                raise_api_error("webhook_evaluation_error", details={"reason": str(exc)})

    @router.post("/integrations/jira/webhook", summary="Jira webhook policy evaluation")
    async def integrations_jira_webhook(
        request: Request,
    ) -> dict | Response:
        if state.jira_connector is None:
            raise_api_error("jira_mapping_not_configured")
        raw_body = await request.body()
        try:
            payload = integration_service.decode_json_body(raw_body)
        except json.JSONDecodeError:
            raise_api_error(
                "validation_error", details={"reason": "Malformed JSON body"}
            )

        key = request.headers.get("Idempotency-Key")
        with idempotency_key_lock(key):
            if key:
                existing = state.processing_store.get_idempotency_entry(key)
                if existing is not None:
                    cached_response, fingerprint = existing
                    incoming_fingerprint = idempotency_request_fingerprint(request, payload)
                    if (
                        fingerprint is not None
                        and incoming_fingerprint is not None
                        and fingerprint != incoming_fingerprint
                    ):
                        raise_api_error(
                            "validation_error",
                            message="Idempotency-Key has already been used with a different payload.",
                            details={"reason": "idempotency_key_conflict"},
                            status_code=409,
                        )
                    return Response(
                        content=cached_response,
                        media_type="application/json",
                        status_code=200,
                    )
            try:
                state.metrics.observe_connector_inbound_event_received(
                    connector="jira",
                    event_type=str(payload.get("webhookEvent") or "unknown"),
                )
                logger.info(
                    "connector_inbound_event_received",
                    connector="jira",
                    event_type=str(payload.get("webhookEvent") or "unknown"),
                )
                result = state.processing_service.enqueue_and_process(
                    {
                        "event_type": "jira_webhook",
                        "headers": dict(request.headers.items()),
                        "payload": payload,
                        "raw_body": raw_body.decode("utf-8"),
                    }
                )
                persist_idempotency_response(request, result, request_payload=payload)
                return _ok(result)
            except QueueOverflowError as exc:
                raise_api_error("rate_limited", details={"reason": str(exc)})
            except LookupError as exc:
                raise_api_error(
                    "jira_policy_bundle_not_found",
                    details=_connector_error_details(
                        connector="jira",
                        stage="bundle_resolution",
                        reason="mapped policy bundle is not loaded",
                        required_bundle=str(exc),
                        loaded_bundle=state.metadata.bundle_name,
                    ),
                )
            except JiraIntegrationError as exc:
                reason = str(exc)
                if "duplicate delivery" in reason:
                    return {
                        "status": "duplicate_ignored",
                        **error_payload(
                            "jira_duplicate_delivery",
                            reason,
                            request.state.request_id,
                            details=_connector_error_details(
                                connector="jira",
                                stage="idempotency",
                                reason=reason,
                            ),
                        ),
                    }
                if "idempotency payload conflict" in reason:
                    raise_api_error(
                        "validation_error",
                        message="Delivery idempotency key has already been used with a different semantic payload.",
                        details={"reason": "delivery_idempotency_payload_conflict"},
                        status_code=409,
                    )
                if "unsupported jira event type" in reason:
                    raise_api_error(
                        "jira_unsupported_event_type", details={"reason": reason}
                    )
                if (
                    "missing required fields" in reason
                    or "missing actor identity" in reason
                ):
                    raise_api_error(
                        "jira_missing_required_fields",
                        details=_connector_error_details(
                            connector="jira",
                            stage="normalization",
                            reason=reason,
                        ),
                    )
                if "signature" in reason:
                    signature_error = (
                        "missing_signature"
                        if "missing webhook signature" in reason
                        else "invalid_signature"
                    )
                    raise_api_error(
                        "jira_authentication_failed",
                        details=_connector_error_details(
                            connector="jira",
                            stage="verification",
                            reason=reason,
                            signature_error=signature_error,
                        ),
                    )
                state.processing_store.enqueue_dead_letter(
                    _integration_dead_letter_event(
                        event_type="jira_webhook",
                        payload=payload,
                        headers=dict(request.headers.items()),
                        raw_body=raw_body,
                    ),
                    reason,
                )
                raise_api_error(
                    "jira_invalid_mapping",
                    details=_connector_error_details(
                        connector="jira",
                        stage="normalization",
                        reason=reason,
                    ),
                )
            except Exception as exc:  # pragma: no cover
                state.processing_store.enqueue_dead_letter(
                    _integration_dead_letter_event(
                        event_type="jira_webhook",
                        payload=payload,
                        headers=dict(request.headers.items()),
                        raw_body=raw_body,
                    ),
                    str(exc),
                )
                raise_api_error(
                    "jira_evaluation_error",
                    details=_connector_error_details(
                        connector="jira",
                        stage="evaluation",
                        reason=str(exc),
                    ),
                )

    @router.post("/integrations/servicenow/webhook", summary="ServiceNow webhook policy evaluation")
    async def integrations_servicenow_webhook(
        request: Request,
        strict_require_allow: bool = False,
    ) -> dict | Response:
        if state.servicenow_connector is None:
            raise_api_error("servicenow_mapping_not_configured")
        raw_body = await request.body()
        try:
            payload = integration_service.decode_json_body(raw_body)
        except json.JSONDecodeError:
            raise_api_error(
                "validation_error", details={"reason": "Malformed JSON body"}
            )

        key = request.headers.get("Idempotency-Key")
        with idempotency_key_lock(key):
            if key:
                existing = state.processing_store.get_idempotency_entry(key)
                if existing is not None:
                    cached_response, fingerprint = existing
                    incoming_fingerprint = idempotency_request_fingerprint(request, payload)
                    if (
                        fingerprint is not None
                        and incoming_fingerprint is not None
                        and fingerprint != incoming_fingerprint
                    ):
                        raise_api_error(
                            "validation_error",
                            message="Idempotency-Key has already been used with a different payload.",
                            details={"reason": "idempotency_key_conflict"},
                            status_code=409,
                        )
                    return Response(
                        content=cached_response,
                        media_type="application/json",
                        status_code=200,
                    )
            try:
                state.metrics.observe_connector_inbound_event_received(
                    connector="servicenow",
                    event_type=str(payload.get("event_type") or payload.get("type") or "unknown"),
                )
                logger.info(
                    "connector_inbound_event_received",
                    connector="servicenow",
                    event_type=str(payload.get("event_type") or payload.get("type") or "unknown"),
                )
                result = state.processing_service.enqueue_and_process(
                    {
                        "event_type": "servicenow_webhook",
                        "headers": dict(request.headers.items()),
                        "payload": payload,
                        "raw_body": raw_body.decode("utf-8"),
                        "strict_require_allow": strict_require_allow,
                    }
                )
                persist_idempotency_response(request, result, request_payload=payload)
                return _ok(result)
            except QueueOverflowError as exc:
                raise_api_error("rate_limited", details={"reason": str(exc)})
            except LookupError as exc:
                raise_api_error(
                    "servicenow_policy_bundle_not_found",
                    details=_connector_error_details(
                        connector="servicenow",
                        stage="bundle_resolution",
                        reason="mapped policy bundle is not loaded",
                        required_bundle=str(exc),
                        loaded_bundle=state.metadata.bundle_name,
                    ),
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
                            details=_connector_error_details(
                                connector="servicenow",
                                stage="idempotency",
                                reason=reason,
                            ),
                        ),
                    }
                if "idempotency payload conflict" in reason:
                    raise_api_error(
                        "validation_error",
                        message="Delivery idempotency key has already been used with a different semantic payload.",
                        details={"reason": "delivery_idempotency_payload_conflict"},
                        status_code=409,
                    )
                if "unsupported servicenow event type" in reason:
                    raise_api_error(
                        "servicenow_unsupported_event_type",
                        details=_connector_error_details(
                            connector="servicenow",
                            stage="normalization",
                            reason=reason,
                        ),
                    )
                if (
                    "missing required fields" in reason
                    or "missing actor identity" in reason
                ):
                    raise_api_error(
                        "servicenow_missing_required_fields",
                        details=_connector_error_details(
                            connector="servicenow",
                            stage="normalization",
                            reason=reason,
                        ),
                    )
                if "signature" in reason:
                    signature_error = (
                        "missing_signature"
                        if "missing webhook signature" in reason
                        else "invalid_signature"
                    )
                    raise_api_error(
                        "servicenow_authentication_failed",
                        details=_connector_error_details(
                            connector="servicenow",
                            stage="verification",
                            reason=reason,
                            signature_error=signature_error,
                        ),
                    )
                state.processing_store.enqueue_dead_letter(
                    _integration_dead_letter_event(
                        event_type="servicenow_webhook",
                        payload=payload,
                        headers=dict(request.headers.items()),
                        raw_body=raw_body,
                        strict_require_allow=strict_require_allow,
                    ),
                    reason,
                )
                raise_api_error(
                    "servicenow_invalid_mapping",
                    details=_connector_error_details(
                        connector="servicenow",
                        stage="normalization",
                        reason=reason,
                    ),
                )
            except Exception as exc:  # pragma: no cover
                state.processing_store.enqueue_dead_letter(
                    _integration_dead_letter_event(
                        event_type="servicenow_webhook",
                        payload=payload,
                        headers=dict(request.headers.items()),
                        raw_body=raw_body,
                        strict_require_allow=strict_require_allow,
                    ),
                    str(exc),
                )
                raise_api_error(
                    "servicenow_evaluation_error",
                    details=_connector_error_details(
                        connector="servicenow",
                        stage="evaluation",
                        reason=str(exc),
                    ),
                )

    @router.get("/admin/dlq", summary="List dead-letter queue items")
    def admin_dlq(limit: int = 100) -> dict:
        return _list_response(state.processing_store.list_dead_letters(limit=limit))

    @router.post("/admin/dlq/retry", summary="Retry dead-letter queue items")
    def admin_dlq_retry(ids: list[int] | None = None) -> dict:
        retry_count = state.processing_store.force_retry(ids)
        if state.dlq_worker is not None:
            state.dlq_worker.run_once()
        return _ok({"retried": retry_count})

    @router.get("/admin/data-access", summary="List governed data access events")
    def admin_data_access(limit: int = 100) -> dict:
        return _list_response(state.processing_store.list_data_access_events(limit=limit))

    @router.get(
        "/integrations/{connector}/admin/outbound/completions",
        summary="List outbound delivery completion records",
    )
    def admin_outbound_completions(connector: str, limit: int = _DEFAULT_LIST_LIMIT) -> dict:
        selected = _configured_connector(connector)
        requested_limit, effective_limit = _bounded_limit(limit)
        return _list_response(
            selected.outbound_completion_records(limit=effective_limit),
            requested_limit=requested_limit,
            limit=effective_limit,
            truncated=requested_limit > effective_limit,
        )

    @router.get(
        "/integrations/{connector}/admin/outbound/dead-letter",
        summary="List outbound delivery dead-letter records",
    )
    def admin_outbound_dead_letter(connector: str, limit: int = _DEFAULT_LIST_LIMIT) -> dict:
        selected = _configured_connector(connector)
        requested_limit, effective_limit = _bounded_limit(limit)
        return _list_response(
            selected.outbound_dead_letter_records(limit=effective_limit),
            requested_limit=requested_limit,
            limit=effective_limit,
            truncated=requested_limit > effective_limit,
        )

    @router.post(
        "/integrations/{connector}/admin/outbound/dead-letter/replay",
        summary="Replay outbound dead-letter records",
    )
    def admin_outbound_dead_letter_replay(connector: str, ids: list[int]) -> dict:
        return _bulk_dead_letter_action(
            connector=connector,
            ids=ids,
            action_name="replay",
            action_fn=lambda selected, dead_letter_id: selected.replay_dead_letter(
                dead_letter_id
            ),
        )

    @router.post(
        "/integrations/{connector}/admin/outbound/dead-letter/manual-redrive",
        summary="Manually mark outbound dead-letter records as redriven",
    )
    def admin_outbound_dead_letter_manual_redrive(
        connector: str, ids: list[int], note: str = "manually redriven"
    ) -> dict:
        normalized_note = _normalize_note(note)
        result = _bulk_dead_letter_action(
            connector=connector,
            ids=ids,
            action_name="manual_redrive",
            action_fn=lambda selected, dead_letter_id: selected.manual_redrive_dead_letter(
                dead_letter_id, note=normalized_note
            ),
        )
        result["note"] = normalized_note
        return result

    @router.get(
        "/integrations/{connector}/admin/outbound/duplicates/summary",
        summary="Summarize duplicate suppression counts",
    )
    def admin_outbound_duplicate_summary(connector: str) -> dict:
        selected = _configured_connector(connector)
        return _ok(selected.outbound_duplicate_suppression_summary())

    @router.get(
        "/integrations/{connector}/admin/outbound/reliability/summary",
        summary="Summarize connector outbound reliability counts",
    )
    def admin_outbound_reliability_summary(connector: str) -> dict:
        selected = _configured_connector(connector)
        if not hasattr(selected, "outbound_reliability_summary"):
            return _ok({})
        return _ok(selected.outbound_reliability_summary())

    @router.get("/admin/slo", summary="Production SLO targets")
    def admin_slo() -> dict:
        reliability = state.reliability_service
        if reliability is None:
            return _ok({"slo_definitions": []})
        return _ok(reliability.slo_payload())

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
        return _list_response(items)

    @router.post("/admin/data/payloads/{payload_id}/hold", summary="Apply legal hold to governed payload")
    def admin_data_payload_hold(payload_id: int, reason: str = "legal_hold") -> dict:
        updated = state.processing_store.apply_governed_payload_legal_hold(
            payload_id,
            reason=reason,
        )
        return _ok({"payload_id": payload_id, "held": updated})

    @router.post("/admin/audit/config", summary="Update audit verification controls")
    def admin_audit_config(payload: dict[str, bool], request: Request) -> dict:
        principal = getattr(request.state, "auth_principal", None)
        decision = evaluate_sensitive_operation(
            operation="audit_config_change",
            principal=principal,
            headers=request.headers,
        )
        if not decision.allowed:
            raise_api_error("forbidden", details=decision.details())
        return _ok(
            {
            "status": "accepted",
            "requested_changes": payload,
            "requires_restart": True,
            }
        )

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
            return _ok(integration_service.handle_slack_interaction(payload_json))
        except SlackIntegrationError as exc:
            raise_api_error("slack_interaction_error", details={"reason": str(exc)})
        except Exception as exc:  # pragma: no cover
            raise_api_error("slack_interaction_error", details={"reason": str(exc)})

    return router
