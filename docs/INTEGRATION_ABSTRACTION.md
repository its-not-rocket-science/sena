# Unified Enterprise Integration Abstraction

## Interface definitions

### Core contracts

- `ApprovalConnectorBase`: shared inbound pipeline (`verify -> route -> idempotency -> normalize -> map_to_proposal`).
- `ApprovalConnectorConfig`: minimal route container used by every connector.
- `MinimalApprovalEventContract`: minimum deterministic event contract consumed by SENA policy evaluation.
- `parse_approval_routes` + `load_mapping_document`: shared mapping parser to remove per-connector config duplication.

```python
class MinimalApprovalEventContract(BaseModel):
    schema_version: str = "1"
    source_system: str
    source_event_type: str
    request_id: str
    requested_action: str
    actor_id: str
    correlation_key: str
    idempotency_key: str
```

## Before / After structure

### Before

- `jira.py`
  - local mapping parser
  - local webhook envelope validation
  - local normalize + proposal plumbing
- `servicenow.py`
  - local mapping parser (mostly same as Jira)
  - local webhook envelope validation (mostly same as Jira)
  - local normalize + proposal plumbing (mostly same as Jira)

### After

- `approval.py`
  - `ApprovalConnectorBase` (shared control flow)
  - `load_mapping_document` + `parse_approval_routes` (shared route parsing)
  - `MinimalApprovalEventContract` (connector-independent minimum event schema)
- `jira.py`
  - Jira-specific delivery modes + Jira-specific event extraction/delivery-id/defaults
- `servicenow.py`
  - ServiceNow-specific delivery modes + ServiceNow-specific event extraction/delivery-id/defaults

## New integration plugin example (<100 LOC)

```python
from dataclasses import dataclass
from sena.integrations.approval import (
    ApprovalConnectorBase, ApprovalConnectorConfig, ApprovalEventRoute,
    InMemoryDeliveryIdempotencyStore, build_normalized_approval_event,
)
from sena.integrations.base import DecisionPayload, IntegrationError

class DemoError(IntegrationError):
    pass

@dataclass(frozen=True)
class DemoConfig:
    routes: dict[str, ApprovalEventRoute]

class DemoConnector(ApprovalConnectorBase):
    name = "demo"
    source_system = "demo"
    error_cls = DemoError
    invalid_envelope_message = "invalid demo event"

    def __init__(self, config: DemoConfig, verifier):
        super().__init__(
            config=ApprovalConnectorConfig(routes=config.routes),
            verifier=verifier,
            idempotency_store=InMemoryDeliveryIdempotencyStore(),
        )

    def extract_event_type(self, payload):
        return str(payload["event_type"])

    def compute_delivery_id(self, *, headers, payload, event_type, route):
        del route
        return str(headers.get("x-request-id") or f"{event_type}:{payload['request_id']}")

    def build_normalized_event(self, *, payload, event_type, route, delivery_id):
        return build_normalized_approval_event(
            payload=payload,
            route=route,
            source_event_type=event_type,
            idempotency_key=delivery_id,
            source_system="demo",
            default_request_id=str(payload["request_id"]),
            default_source_record_id=str(payload["record_id"]),
            error_cls=DemoError,
            default_source_object_type="demo_object",
            default_workflow_stage="requested",
            default_requested_action=route.action_type,
            default_correlation_key=str(payload["request_id"]),
        )

    def send_decision(self, payload: DecisionPayload):
        return {"status": "delivered", "decision_id": payload.decision_id}
```

## Migration plan

1. **Introduce shared abstractions (done):** add `ApprovalConnectorBase`, shared parser utilities, and contract model.
2. **Refactor existing connectors (done):** move Jira/ServiceNow onto shared base while preserving existing connector APIs.
3. **Parity validation (done):** run existing Jira and ServiceNow tests plus contract/base regression tests.
4. **Incremental rollout:**
   - onboard one additional integration (e.g., Workday/Asana) using new base class,
   - keep existing mapping schema stable,
   - instrument delivery-id collision + parse failure metrics.
5. **Deprecation cleanup:**
   - remove remaining duplicated helper code in legacy connectors,
   - keep adapter shims for existing imports until next major version.
