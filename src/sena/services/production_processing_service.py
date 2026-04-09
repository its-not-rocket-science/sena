from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sena.api.data_governance import TenancyContext, scan_and_redact_payload
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

    def _resolve_tenancy_context(
        self, *, tenant_id: str | None, region: str | None
    ) -> TenancyContext:
        resolved_tenant_id = tenant_id or "default"
        resolved_region = region or self.state.settings.data_default_region
        if resolved_region not in set(self.state.settings.data_allowed_regions):
            allowed = sorted(set(self.state.settings.data_allowed_regions))
            raise ValueError(
                f"region '{resolved_region}' is not allowed; expected one of {allowed}"
            )
        return TenancyContext(tenant_id=resolved_tenant_id, region=resolved_region)

    def _store_governed_payload(
        self,
        *,
        tenancy: TenancyContext,
        payload_type: str,
        payload: dict[str, Any],
    ) -> None:
        pii = scan_and_redact_payload(payload)
        self.state.processing_store.purge_expired_governed_payloads()
        self.state.processing_store.store_governed_payload(
            tenant_id=tenancy.tenant_id,
            region=tenancy.region,
            payload_type=payload_type,
            payload=payload,
            redacted_payload=pii.redacted_payload,
            pii_flags=list(pii.flagged_fields),
            ttl_hours=self.state.settings.payload_retention_ttl_hours,
        )

    def process_evaluate(self, payload: dict[str, Any], *, request_id: str) -> dict[str, Any]:
        req = EvaluateRequest.model_validate(payload)
        tenancy = self._resolve_tenancy_context(
            tenant_id=req.tenant_id,
            region=req.region or str(req.facts.get("region") or ""),
        )
        self._store_governed_payload(
            tenancy=tenancy,
            payload_type="evaluate_request",
            payload=req.model_dump(),
        )
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
            simulate_exceptions=req.simulate_exceptions,
        )

    def process_webhook(self, payload: dict[str, Any], *, request_id: str) -> dict[str, Any]:
        req = WebhookEvaluateRequest.model_validate(payload)
        tenancy = self._resolve_tenancy_context(
            tenant_id=req.tenant_id,
            region=req.region or str(req.facts.get("region") or ""),
        )
        self._store_governed_payload(
            tenancy=tenancy,
            payload_type="webhook_request",
            payload=req.model_dump(),
        )
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
