from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from sena.integrations.approval import (
    ApprovalConnectorBase,
    ApprovalConnectorConfig,
    ApprovalEventRoute,
    DeliveryRetryError,
    InMemoryDeadLetterQueue,
    InMemoryDeliveryIdempotencyStore,
    InMemoryDeliveryExecutionStore,
    MinimalApprovalEventContract,
    NormalizedApprovalEvent,
    ReliableDeliveryExecutor,
    build_normalized_approval_event,
    load_mapping_document,
    parse_approval_routes,
    resolve_path,
)
from sena.api.logging import get_logger
from sena.integrations.base import DecisionPayload, IntegrationError
from sena.integrations.persistence import SQLiteIntegrationReliabilityStore

logger = get_logger(__name__)

class JiraIntegrationError(IntegrationError):
    """Raised for deterministic Jira integration failures."""


JiraEventRoute = ApprovalEventRoute


@dataclass(frozen=True)
class JiraOutboundConfig:
    mode: str = "comment"
    max_attempts: int = 1


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
        provided = _extract_jira_signature(headers=headers, signature_header=self._signature_header)
        if not provided:
            raise JiraIntegrationError(
                "missing webhook signature (expected header: x-sena-signature or x-hub-signature-256)"
            )
        expected = hmac.new(self._secret, raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(provided, expected):
            raise JiraIntegrationError("invalid webhook signature")


class RotatingSharedSecretJiraWebhookVerifier:
    def __init__(
        self, secrets: tuple[str, ...], signature_header: str = "x-sena-signature"
    ) -> None:
        self._secrets = tuple(secret.encode("utf-8") for secret in secrets if secret)
        self._signature_header = signature_header.lower()

    def verify(self, *, headers: dict[str, str], raw_body: bytes) -> None:
        provided = _extract_jira_signature(headers=headers, signature_header=self._signature_header)
        if not provided:
            raise JiraIntegrationError(
                "missing webhook signature (expected header: x-sena-signature or x-hub-signature-256)"
            )
        for secret in self._secrets:
            expected = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
            if hmac.compare_digest(provided, expected):
                return
        raise JiraIntegrationError("invalid webhook signature")


def _extract_jira_signature(*, headers: dict[str, str], signature_header: str) -> str:
    direct = str(headers.get(signature_header, "")).strip()
    if direct:
        return direct
    prefixed = str(headers.get("x-hub-signature-256", "")).strip()
    if prefixed.lower().startswith("sha256="):
        return prefixed.split("=", 1)[1].strip()
    return prefixed


class JiraIdempotencyStore(Protocol):
    def mark_if_new(self, delivery_id: str) -> bool: ...


InMemoryJiraIdempotencyStore = InMemoryDeliveryIdempotencyStore
NormalizedJiraEvent = NormalizedApprovalEvent


def load_jira_mapping_config(path: str) -> JiraMappingConfig:
    raw = load_mapping_document(path)
    routes = parse_approval_routes(raw, error_cls=JiraIntegrationError, config_name="Jira")
    outbound_raw = raw.get("outbound", {}) or {}
    mode = str(outbound_raw.get("mode", "comment"))
    max_attempts = int(outbound_raw.get("max_attempts", 1))
    if mode not in {"comment", "status", "both", "none"}:
        raise JiraIntegrationError(
            "Jira outbound.mode must be one of: comment,status,both,none"
        )
    return JiraMappingConfig(
        routes=routes,
        outbound=JiraOutboundConfig(mode=mode, max_attempts=max_attempts),
    )


class JiraDeliveryClient(Protocol):
    def publish_comment(self, issue_key: str, message: str) -> dict[str, Any]: ...

    def publish_status(self, issue_key: str, payload: dict[str, Any]) -> dict[str, Any]: ...


class NullJiraDeliveryClient:
    def publish_comment(self, issue_key: str, message: str) -> dict[str, Any]:
        return {"status": "skipped", "target": "comment", "issue_key": issue_key}

    def publish_status(self, issue_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"status": "skipped", "target": "status", "issue_key": issue_key}


class JiraConnector(ApprovalConnectorBase):
    name = "jira"
    source_system = "jira"
    error_cls = JiraIntegrationError
    invalid_envelope_message = "invalid jira event envelope"

    def __init__(
        self,
        *,
        config: JiraMappingConfig,
        verifier: JiraWebhookVerifier,
        idempotency_store: JiraIdempotencyStore | None = None,
        reliability_store: SQLiteIntegrationReliabilityStore | None = None,
        reliability_db_path: str | None = None,
        require_durable_reliability: bool = False,
        delivery_client: JiraDeliveryClient | None = None,
        reliability_observer: Any | None = None,
    ) -> None:
        durable_store = reliability_store
        if durable_store is None and reliability_db_path:
            durable_store = SQLiteIntegrationReliabilityStore(str(Path(reliability_db_path)))
        if require_durable_reliability and durable_store is None:
            raise JiraIntegrationError(
                "durable reliability storage is required; "
                "configure reliability_store or reliability_db_path"
            )
        super().__init__(
            config=ApprovalConnectorConfig(routes=config.routes),
            verifier=verifier,
            idempotency_store=idempotency_store
            or durable_store
            or InMemoryJiraIdempotencyStore(),
            reliability_observer=reliability_observer,
        )
        self._config = config
        self._reliability_store = durable_store
        self._delivery_client = delivery_client or NullJiraDeliveryClient()
        self._delivery_executor = ReliableDeliveryExecutor(
            max_attempts=config.outbound.max_attempts,
            completion_store=durable_store or InMemoryDeliveryExecutionStore(),
            dlq=durable_store or InMemoryDeadLetterQueue(),
            reliability_observer=reliability_observer,
        )
        self._reliability_observer = reliability_observer

    def dead_letter_items(self) -> list[dict[str, Any]]:
        return [item.__dict__.copy() for item in self._delivery_executor.dlq.items()]

    def outbound_completion_records(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if self._reliability_store is None:
            return []
        return [record.__dict__.copy() for record in self._reliability_store.list_completion_records(limit=limit)]

    def outbound_dead_letter_records(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if self._reliability_store is None:
            return []
        return [record.__dict__.copy() for record in self._reliability_store.list_dead_letter_records(limit=limit)]

    def outbound_duplicate_suppression_summary(self) -> dict[str, Any]:
        if self._reliability_store is None:
            return {"inbound": {}, "outbound": {}}
        return self._reliability_store.duplicate_suppression_summary()

    def outbound_reliability_summary(self) -> dict[str, Any]:
        if self._reliability_store is None:
            return {}
        return self._reliability_store.reliability_summary()

    def replay_dead_letter(self, dead_letter_id: int) -> dict[str, Any]:
        if self._reliability_store is None:
            raise JiraIntegrationError("durable reliability storage is not configured")
        record = self._reliability_store.get_dead_letter_record(dead_letter_id)
        if record is None:
            raise JiraIntegrationError(f"dead-letter record not found: {dead_letter_id}")
        try:
            if record.target == "comment":
                issue_key = str(record.payload.get("issue_key") or "")
                message = str(record.payload.get("message") or "")
                result = self._delivery_client.publish_comment(issue_key, message)
            elif record.target == "status":
                issue_key = str(record.payload.get("issue_key") or "")
                result = self._delivery_client.publish_status(issue_key, record.payload)
            else:
                raise JiraIntegrationError(f"unsupported dead-letter target: {record.target}")
        except Exception:
            self._reliability_store.record_admin_event(
                event_type="replay",
                target=record.target,
                status="failure",
            )
            if self._reliability_observer is not None:
                self._reliability_observer.record_outbound_replay(
                    target=record.target, status="failure"
                )
            logger.warning(
                "connector_outbound_dead_letter_replay_failed",
                connector=self.source_system,
                target=record.target,
                dead_letter_id=dead_letter_id,
            )
            raise
        self._reliability_store.mark_completed(
            record.operation_key,
            target=record.target,
            payload=record.payload,
            result=result if isinstance(result, dict) else {"value": result},
            attempts=record.attempts,
            max_attempts=record.max_attempts or self._config.outbound.max_attempts,
        )
        self._reliability_store.delete_dead_letter_record(dead_letter_id)
        self._reliability_store.record_admin_event(
            event_type="replay", target=record.target, status="success"
        )
        if self._reliability_observer is not None:
            self._reliability_observer.record_outbound_replay(
                target=record.target, status="success"
            )
            self._reliability_observer.record_outbound_completion(target=record.target)
            self._reliability_observer.record_outbound_dead_letter_removed()
        logger.info(
            "connector_outbound_dead_letter_replayed",
            connector=self.source_system,
            target=record.target,
            dead_letter_id=dead_letter_id,
        )
        return {"dead_letter_id": dead_letter_id, "status": "replayed", "result": result}

    def manual_redrive_dead_letter(self, dead_letter_id: int, *, note: str) -> dict[str, Any]:
        if self._reliability_store is None:
            raise JiraIntegrationError("durable reliability storage is not configured")
        record = self._reliability_store.get_dead_letter_record(dead_letter_id)
        if record is None:
            raise JiraIntegrationError(f"dead-letter record not found: {dead_letter_id}")
        self._reliability_store.mark_completed(
            record.operation_key,
            target=record.target,
            payload=record.payload,
            result={"status": "manually_redriven", "note": note},
            attempts=record.attempts,
            max_attempts=record.max_attempts or self._config.outbound.max_attempts,
        )
        self._reliability_store.delete_dead_letter_record(dead_letter_id)
        self._reliability_store.record_admin_event(
            event_type="manual_redrive", target=record.target, status="success"
        )
        if self._reliability_observer is not None:
            self._reliability_observer.record_outbound_manual_redrive(
                target=record.target
            )
            self._reliability_observer.record_outbound_completion(target=record.target)
            self._reliability_observer.record_outbound_dead_letter_removed()
        logger.info(
            "connector_outbound_dead_letter_manual_redrive",
            connector=self.source_system,
            target=record.target,
            dead_letter_id=dead_letter_id,
            note=note,
        )
        return {"dead_letter_id": dead_letter_id, "status": "manually_redriven"}

    def send_decision(self, payload: DecisionPayload) -> dict[str, Any]:
        issue_key = payload.request_id or "unknown"
        message = (
            f"SENA decision={payload.summary} decision_id={payload.decision_id} "
            f"merkle_proof={payload.merkle_proof or 'na'} rules={','.join(payload.matched_rule_ids)}"
        )
        mode = self._config.outbound.mode
        results: list[dict[str, Any]] = []
        errors: list[str] = []
        if mode in {"comment", "both"}:
            try:
                results.append(
                    self._delivery_executor.deliver(
                        operation_key=f"{payload.decision_id}:comment:{issue_key}",
                        target="comment",
                        payload={"issue_key": issue_key, "message": message},
                        delivery_fn=lambda: self._delivery_client.publish_comment(
                            issue_key, message
                        ),
                    )
                )
            except DeliveryRetryError as exc:
                errors.append(f"comment:{exc}")
        if mode in {"status", "both"}:
            decision_state = payload.summary.lower()
            route = next(iter(self._config.routes.values()), None)
            external_state = (
                route.internal_to_external_state.get(decision_state, decision_state)
                if route
                else decision_state
            )
            try:
                results.append(
                    self._delivery_executor.deliver(
                        operation_key=f"{payload.decision_id}:status:{issue_key}",
                        target="status",
                        payload={
                            "issue_key": issue_key,
                            "decision_id": payload.decision_id,
                            "action_type": payload.action_type,
                            "matched_rule_ids": payload.matched_rule_ids,
                            "summary": payload.summary,
                            "external_state": external_state,
                        },
                        delivery_fn=lambda: self._delivery_client.publish_status(
                            issue_key,
                            {
                                "decision_id": payload.decision_id,
                                "action_type": payload.action_type,
                                "matched_rule_ids": payload.matched_rule_ids,
                                "summary": payload.summary,
                                "external_state": external_state,
                            },
                        ),
                    )
                )
            except DeliveryRetryError as exc:
                errors.append(f"status:{exc}")
        if errors:
            return {"status": "partial_failure", "results": results, "errors": errors}
        return {"status": "delivered", "results": results}

    def extract_event_type(self, payload: dict[str, Any]) -> str:
        event_type = str(payload.get("webhookEvent") or "").strip()
        if not event_type:
            raise JiraIntegrationError("missing webhookEvent")
        return event_type

    def compute_delivery_id(
        self,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        event_type: str,
        route: JiraEventRoute,
    ) -> str:
        del route
        issue_id = str(resolve_path(payload, "issue.id", error_cls=JiraIntegrationError))
        return (
            headers.get("x-atlassian-webhook-identifier")
            or headers.get("x-request-id")
            or f"{event_type}:{payload.get('timestamp')}:{issue_id}"
        )

    def build_normalized_event(
        self,
        *,
        payload: dict[str, Any],
        event_type: str,
        route: JiraEventRoute,
        delivery_id: str,
    ) -> NormalizedJiraEvent:
        issue_id = str(resolve_path(payload, "issue.id", error_cls=JiraIntegrationError))
        issue_key = str(resolve_path(payload, "issue.key", error_cls=JiraIntegrationError))
        normalized = build_normalized_approval_event(
            payload=payload,
            route=route,
            source_event_type=event_type,
            idempotency_key=delivery_id,
            source_system="jira",
            default_request_id=issue_key,
            default_source_record_id=issue_id,
            error_cls=JiraIntegrationError,
            default_source_object_type="jira_issue",
            default_workflow_stage="pending_approval",
            default_requested_action=route.action_type,
            default_correlation_key=issue_key,
            source_metadata={"jira_issue_key": issue_key},
        )
        MinimalApprovalEventContract(
            source_system=normalized.source_system,
            source_event_type=normalized.source_event_type,
            request_id=normalized.request_id,
            requested_action=normalized.requested_action,
            actor_id=normalized.actor.actor_id,
            correlation_key=normalized.correlation_key,
            idempotency_key=normalized.idempotency_key,
        )
        return normalized
