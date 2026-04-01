from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Protocol

from sena.integrations.approval import (
    ApprovalEventRoute,
    InMemoryDeliveryIdempotencyStore,
    NormalizedApprovalEvent,
    build_normalized_approval_event,
    resolve_path,
    to_action_proposal,
)
from sena.integrations.base import Connector, DecisionPayload, IntegrationError


class JiraIntegrationError(IntegrationError):
    """Raised for deterministic Jira integration failures."""


JiraEventRoute = ApprovalEventRoute


@dataclass(frozen=True)
class JiraOutboundConfig:
    mode: str = "comment"


@dataclass(frozen=True)
class JiraMappingConfig:
    routes: dict[str, JiraEventRoute]
    outbound: JiraOutboundConfig = JiraOutboundConfig()


class JiraWebhookVerifier(Protocol):
    def verify(self, *, headers: dict[str, str], raw_body: bytes) -> None: ...


class AllowAllJiraWebhookVerifier:
    def verify(self, *, headers: dict[str, str], raw_body: bytes) -> None:
        return None


class SharedSecretJiraWebhookVerifier:
    """Simple pluggable verifier contract using HMAC SHA256."""

    def __init__(self, secret: str, signature_header: str = "x-sena-signature") -> None:
        self._secret = secret.encode("utf-8")
        self._signature_header = signature_header.lower()

    def verify(self, *, headers: dict[str, str], raw_body: bytes) -> None:
        provided = headers.get(self._signature_header, "")
        if not provided:
            raise JiraIntegrationError("missing webhook signature")
        expected = hmac.new(self._secret, raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(provided, expected):
            raise JiraIntegrationError("invalid webhook signature")


class JiraIdempotencyStore(Protocol):
    def mark_if_new(self, delivery_id: str) -> bool: ...


InMemoryJiraIdempotencyStore = InMemoryDeliveryIdempotencyStore
NormalizedJiraEvent = NormalizedApprovalEvent


def load_jira_mapping_config(path: str) -> JiraMappingConfig:
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError:
        yaml = None

    text = open(path, encoding="utf-8").read()
    raw = yaml.safe_load(text) if yaml else json.loads(text)
    routes_raw = raw.get("routes")
    if not isinstance(routes_raw, dict) or not routes_raw:
        raise JiraIntegrationError("Jira mapping config must define non-empty routes")

    routes: dict[str, JiraEventRoute] = {}
    for event_type, route in routes_raw.items():
        if not isinstance(route, dict):
            raise JiraIntegrationError(f"route '{event_type}' must be an object")
        if "action_type" not in route or "actor_id_path" not in route:
            raise JiraIntegrationError(f"route '{event_type}' missing required keys")
        attrs = route.get("attributes", {})
        if not isinstance(attrs, dict):
            raise JiraIntegrationError(f"route '{event_type}' attributes must be an object")
        required_fields = route.get("required_fields", [])
        if not isinstance(required_fields, list):
            raise JiraIntegrationError(f"route '{event_type}' required_fields must be a list")
        routes[event_type] = JiraEventRoute(
            action_type=str(route["action_type"]),
            actor_id_path=str(route["actor_id_path"]),
            attributes={str(k): str(v) for k, v in attrs.items()},
            required_fields=[str(item) for item in required_fields],
            static_attributes=route.get("static_attributes", {}) or {},
            request_id_path=route.get("request_id_path"),
            actor_role_path=route.get("actor_role_path"),
            source_record_id_path=route.get("source_record_id_path"),
            policy_bundle=route.get("policy_bundle"),
        )
    outbound_raw = raw.get("outbound", {}) or {}
    mode = str(outbound_raw.get("mode", "comment"))
    if mode not in {"comment", "status", "both", "none"}:
        raise JiraIntegrationError("Jira outbound.mode must be one of: comment,status,both,none")
    return JiraMappingConfig(routes=routes, outbound=JiraOutboundConfig(mode=mode))


class JiraDeliveryClient(Protocol):
    def publish_comment(self, issue_key: str, message: str) -> dict[str, Any]: ...

    def publish_status(self, issue_key: str, payload: dict[str, Any]) -> dict[str, Any]: ...


class NullJiraDeliveryClient:
    def publish_comment(self, issue_key: str, message: str) -> dict[str, Any]:
        return {"status": "skipped", "target": "comment", "issue_key": issue_key}

    def publish_status(self, issue_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"status": "skipped", "target": "status", "issue_key": issue_key}


class JiraConnector(Connector):
    name = "jira"

    def __init__(
        self,
        *,
        config: JiraMappingConfig,
        verifier: JiraWebhookVerifier,
        idempotency_store: JiraIdempotencyStore | None = None,
        delivery_client: JiraDeliveryClient | None = None,
    ) -> None:
        self._config = config
        self._verifier = verifier
        self._idempotency = idempotency_store or InMemoryJiraIdempotencyStore()
        self._delivery_client = delivery_client or NullJiraDeliveryClient()

    def handle_event(self, event: dict[str, Any]) -> dict[str, Any]:
        headers = event.get("headers") or {}
        payload = event.get("payload") or {}
        raw_body = event.get("raw_body") or b""
        if not isinstance(headers, dict) or not isinstance(payload, dict) or not isinstance(raw_body, bytes):
            raise JiraIntegrationError("invalid jira event envelope")
        normalized = self.normalize_event(headers=headers, payload=payload, raw_body=raw_body)
        proposal = self.map_to_proposal(normalized)
        return {"normalized_event": normalized.model_dump(), "action_proposal": proposal}

    def send_decision(self, payload: DecisionPayload) -> dict[str, Any]:
        issue_key = payload.request_id or "unknown"
        message = f"SENA decision={payload.summary} decision_id={payload.decision_id} rules={','.join(payload.matched_rule_ids)}"
        mode = self._config.outbound.mode
        results: list[dict[str, Any]] = []
        errors: list[str] = []
        if mode in {"comment", "both"}:
            try:
                results.append(self._delivery_client.publish_comment(issue_key, message))
            except Exception as exc:  # pragma: no cover
                errors.append(f"comment:{exc}")
        if mode in {"status", "both"}:
            try:
                results.append(
                    self._delivery_client.publish_status(
                        issue_key,
                        {
                            "decision_id": payload.decision_id,
                            "action_type": payload.action_type,
                            "matched_rule_ids": payload.matched_rule_ids,
                            "summary": payload.summary,
                        },
                    )
                )
            except Exception as exc:  # pragma: no cover
                errors.append(f"status:{exc}")
        if errors:
            return {"status": "partial_failure", "results": results, "errors": errors}
        return {"status": "delivered", "results": results}

    def normalize_event(
        self,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        raw_body: bytes,
    ) -> NormalizedJiraEvent:
        lowered_headers = {str(k).lower(): str(v) for k, v in headers.items()}
        self._verifier.verify(headers=lowered_headers, raw_body=raw_body)

        event_type = str(payload.get("webhookEvent") or "").strip()
        if not event_type:
            raise JiraIntegrationError("missing webhookEvent")
        route = self._config.routes.get(event_type)
        if route is None:
            raise JiraIntegrationError(f"unsupported jira event type '{event_type}'")

        issue_id = str(resolve_path(payload, "issue.id", error_cls=JiraIntegrationError))
        delivery_id = (
            lowered_headers.get("x-atlassian-webhook-identifier")
            or lowered_headers.get("x-request-id")
            or f"{event_type}:{payload.get('timestamp')}:{issue_id}"
        )
        if not self._idempotency.mark_if_new(delivery_id):
            raise JiraIntegrationError(f"duplicate delivery '{delivery_id}'")

        return build_normalized_approval_event(
            payload=payload,
            route=route,
            event_type=event_type,
            delivery_id=delivery_id,
            source_system="jira",
            default_request_id=str(resolve_path(payload, "issue.key", error_cls=JiraIntegrationError)),
            default_source_record_id=issue_id,
            error_cls=JiraIntegrationError,
            source_metadata={"jira_issue_key": str(resolve_path(payload, "issue.key", error_cls=JiraIntegrationError))},
        )

    def map_to_proposal(self, event: NormalizedJiraEvent):
        route = self._config.routes[event.event_type]
        return to_action_proposal(event, route)

    def route_for_event_type(self, event_type: str) -> JiraEventRoute | None:
        return self._config.routes.get(event_type)
