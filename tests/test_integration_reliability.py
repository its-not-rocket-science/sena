from __future__ import annotations

from types import SimpleNamespace

from sena.services.integration_service import IntegrationService
from sena.services.reliability_service import InMemoryIngestionQueue, ReliabilityService


class _Store:
    def __init__(self) -> None:
        self.events: list[tuple[dict, str]] = []

    def enqueue_dead_letter(self, event: dict, error: str) -> int:
        self.events.append((event, error))
        return len(self.events)


class _FailingConnector:
    def route_for_event_type(self, _event_type: str):
        return None

    def send_decision(self, _payload):
        raise RuntimeError("integration unavailable")


class _Registry:
    def get(self, name: str):
        if name != "jira":
            raise AssertionError("unexpected connector")

        class _Inbound:
            def handle_event(self, _event):
                proposal = SimpleNamespace(
                    request_id="REQ-1",
                    action_type="approve_vendor_payment",
                    actor_id="actor-1",
                    attributes={},
                )
                return {
                    "normalized_event": {"source_event_type": "jira.issue"},
                    "action_proposal": proposal,
                }

        return _Inbound()


class _Eval:
    def evaluate(self, **_kwargs):
        return {
            "decision_id": "d-1",
            "matched_rules": [{"rule_id": "r-1"}],
            "summary": "approved",
        }


def test_jira_graceful_degradation_returns_fallback_and_queues_retry() -> None:
    store = _Store()
    state = SimpleNamespace(
        connector_registry=_Registry(),
        jira_connector=_FailingConnector(),
        processing_store=store,
        reliability_service=ReliabilityService(ingestion_queue=InMemoryIngestionQueue()),
        metadata=SimpleNamespace(bundle_name="enterprise-demo"),
    )
    service = IntegrationService(state=state, evaluation_service=_Eval())

    result = service.handle_jira_event(headers={}, payload={}, raw_body=b"{}")

    assert result["outbound_delivery"]["status"] == "degraded"
    assert result["outbound_delivery"]["fallback_mode"] == "queue_for_retry"
    assert store.events[0][0]["event_type"] == "integration_outbound_retry"
