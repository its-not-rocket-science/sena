from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException


@dataclass(frozen=True)
class ErrorCatalogEntry:
    http_status: int
    message: str


ERROR_CODE_CATALOG: dict[str, ErrorCatalogEntry] = {
    "validation_error": ErrorCatalogEntry(422, "Request validation failed."),
    "http_bad_request": ErrorCatalogEntry(400, "Request cannot be processed."),
    "http_not_found": ErrorCatalogEntry(404, "Requested resource was not found."),
    "http_internal_error": ErrorCatalogEntry(500, "Internal server error."),
    "invalid_content_length": ErrorCatalogEntry(400, "Invalid Content-Length header."),
    "payload_too_large": ErrorCatalogEntry(413, "Request payload exceeds maximum size."),
    "unauthorized": ErrorCatalogEntry(401, "Missing or invalid API key."),
    "forbidden": ErrorCatalogEntry(403, "API key role is not authorized for this endpoint."),
    "rate_limited": ErrorCatalogEntry(429, "Rate limit exceeded."),
    "timeout": ErrorCatalogEntry(504, "Request processing timed out."),
    "policy_store_unavailable": ErrorCatalogEntry(400, "Policy store backend is not sqlite."),
    "bundle_not_found": ErrorCatalogEntry(404, "Bundle was not found."),
    "active_bundle_not_found": ErrorCatalogEntry(404, "No active bundle found."),
    "promotion_validation_failed": ErrorCatalogEntry(400, "Bundle promotion validation failed."),
    "evaluation_error": ErrorCatalogEntry(400, "Evaluation failed."),
    "webhook_mapping_not_configured": ErrorCatalogEntry(400, "Webhook mapping config is not set."),
    "webhook_mapping_error": ErrorCatalogEntry(400, "Webhook mapping failed."),
    "webhook_evaluation_error": ErrorCatalogEntry(400, "Webhook evaluation failed."),
    "jira_mapping_not_configured": ErrorCatalogEntry(400, "Jira mapping config is not set."),
    "jira_authentication_failed": ErrorCatalogEntry(401, "Jira webhook authenticity check failed."),
    "jira_unsupported_event_type": ErrorCatalogEntry(400, "Unsupported Jira event type."),
    "jira_missing_required_fields": ErrorCatalogEntry(400, "Jira payload missing required fields."),
    "jira_invalid_mapping": ErrorCatalogEntry(400, "Jira mapping is invalid."),
    "jira_duplicate_delivery": ErrorCatalogEntry(200, "Duplicate Jira delivery ignored."),
    "jira_policy_bundle_not_found": ErrorCatalogEntry(404, "Mapped Jira policy bundle was not found."),
    "jira_evaluation_error": ErrorCatalogEntry(400, "Jira evaluation failed."),
    "jira_outbound_delivery_failed": ErrorCatalogEntry(502, "Jira decision delivery failed."),
    "slack_interaction_error": ErrorCatalogEntry(400, "Slack interaction failed."),
    "audit_sink_not_configured": ErrorCatalogEntry(400, "Audit sink not configured."),
}


def raise_api_error(
    code: str,
    *,
    message: str | None = None,
    details: Any | None = None,
    status_code: int | None = None,
) -> None:
    entry = ERROR_CODE_CATALOG.get(code)
    resolved_status = status_code if status_code is not None else (entry.http_status if entry else 500)
    resolved_message = message if message is not None else (entry.message if entry else "Request failed.")
    detail: dict[str, Any] = {"code": code, "message": resolved_message}
    if details is not None:
        detail["details"] = details
    raise HTTPException(status_code=resolved_status, detail=detail)
