from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sena.api.schemas import EvaluateRequest, WebhookEvaluateRequest
from sena.core.enums import DecisionOutcome
from sena.services.audit_service import AuditService
from sena.services.evaluation_service import EvaluationService
from sena.services.integration_service import IntegrationService


@dataclass
class ProductionProcessingService:
    state: Any

    def __post_init__(self) -> None:
        self._evaluation = EvaluationService(
            state=self.state,
            audit_service=AuditService(self.state.settings.audit_sink_jsonl),
        )
        self._integration = IntegrationService(
            state=self.state,
            evaluation_service=self._evaluation,
        )

    def process_evaluate(self, payload: dict[str, Any], *, request_id: str) -> dict[str, Any]:
        req = EvaluateRequest.model_validate(payload)
        proposal = req.to_action_proposal(request_id)
        return self._evaluation.evaluate(
            proposal=proposal,
            facts=req.facts,
            endpoint="/v1/evaluate",
            default_decision=req.to_default_decision(),
            strict_require_allow=req.strict_require_allow,
            notify_on_escalation=not req.dry_run,
            append_audit=not req.dry_run,
            replay_input=req.to_replay_input(request_id),
        )

    def process_webhook(self, payload: dict[str, Any], *, request_id: str) -> dict[str, Any]:
        req = WebhookEvaluateRequest.model_validate(payload)
        return self._integration.handle_webhook_event(
            provider=req.provider,
            event_type=req.event_type,
            payload=req.payload,
            facts=req.facts,
            default_decision=req.to_default_decision(),
            strict_require_allow=req.strict_require_allow,
            default_request_id=request_id,
        )

    def process_jira_webhook(
        self, *, headers: dict[str, str], payload: dict[str, Any], raw_body: bytes
    ) -> dict[str, Any]:
        return self._integration.handle_jira_event(
            headers=headers,
            payload=payload,
            raw_body=raw_body,
        )

    def process_servicenow_webhook(
        self,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        raw_body: bytes,
        strict_require_allow: bool,
    ) -> dict[str, Any]:
        return self._integration.handle_servicenow_event(
            headers=headers,
            payload=payload,
            raw_body=raw_body,
            strict_require_allow=strict_require_allow,
        )

    def process_event(self, event: dict[str, Any]) -> dict[str, Any]:
        event_type = str(event.get("event_type") or "")
        if event_type == "evaluate":
            return self.process_evaluate(
                dict(event.get("payload") or {}),
                request_id=str(event.get("request_id") or "req-dlq"),
            )
        if event_type == "webhook":
            return self.process_webhook(
                dict(event.get("payload") or {}),
                request_id=str(event.get("request_id") or "req-dlq"),
            )
        if event_type == "jira_webhook":
            return self.process_jira_webhook(
                headers=dict(event.get("headers") or {}),
                payload=dict(event.get("payload") or {}),
                raw_body=str(event.get("raw_body") or "").encode("utf-8"),
            )
        if event_type == "servicenow_webhook":
            return self.process_servicenow_webhook(
                headers=dict(event.get("headers") or {}),
                payload=dict(event.get("payload") or {}),
                raw_body=str(event.get("raw_body") or "").encode("utf-8"),
                strict_require_allow=bool(event.get("strict_require_allow") or False),
            )
        raise ValueError(f"unsupported dlq event_type '{event_type}'")

    @staticmethod
    def fallback_default_decision() -> DecisionOutcome:
        return DecisionOutcome.APPROVED
