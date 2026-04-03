import pytest

from sena.integrations.langchain import (
    LangChainIntegrationError,
    SenaApprovalCallback,
    SenaBlockedError,
    SenaDecision,
)


class StubSenaClient:
    def __init__(self, decision: SenaDecision):
        self.decision = decision
        self.last_payload = None

    def evaluate(self, payload):
        self.last_payload = payload
        return self.decision


def test_callback_blocks_tool_call() -> None:
    callback = SenaApprovalCallback(
        sena_endpoint="http://localhost:8000",
        policy_bundle="enterprise-demo:active",
        sena_client=StubSenaClient(
            SenaDecision(
                outcome="BLOCKED",
                evidence="refund amount exceeds policy limit",
                decision_id="dec-1",
                merkle_proof=["a", "b"],
            )
        ),
    )

    with pytest.raises(SenaBlockedError, match="exceeds policy"):
        callback.on_tool_start(
            {"name": "approve_refund"},
            '{"amount": 250}',
            run_id="run-1",
            metadata={},
        )


def test_callback_attaches_decision_metadata_for_allowed_tool() -> None:
    client = StubSenaClient(
        SenaDecision(
            outcome="APPROVED",
            evidence="within threshold",
            decision_id="dec-2",
            merkle_proof=["leaf", "sibling"],
        )
    )
    callback = SenaApprovalCallback(
        sena_endpoint="http://localhost:8000",
        policy_bundle="enterprise-demo:active",
        sena_client=client,
    )
    metadata = {}

    callback.on_tool_start(
        {"name": "approve_refund"},
        '{"amount": 25}',
        run_id="run-2",
        metadata=metadata,
    )

    assert metadata["sena_decision_id"] == "dec-2"
    assert metadata["sena_proof"] == ["leaf", "sibling"]
    assert client.last_payload["attributes"]["policy_bundle"] == "enterprise-demo:active"


def test_callback_requires_tool_name() -> None:
    callback = SenaApprovalCallback(
        sena_endpoint="http://localhost:8000",
        policy_bundle="enterprise-demo:active",
        sena_client=StubSenaClient(
            SenaDecision(
                outcome="APPROVED",
                evidence="ok",
                decision_id="dec-3",
                merkle_proof=[],
            )
        ),
    )

    with pytest.raises(LangChainIntegrationError, match="missing tool name"):
        callback.on_tool_start({}, "{}", metadata={})


def test_callback_requires_dict_metadata() -> None:
    callback = SenaApprovalCallback(
        sena_endpoint="http://localhost:8000",
        policy_bundle="enterprise-demo:active",
        sena_client=StubSenaClient(
            SenaDecision(
                outcome="APPROVED",
                evidence="ok",
                decision_id="dec-4",
                merkle_proof=[],
            )
        ),
    )

    with pytest.raises(LangChainIntegrationError, match="must be a dictionary"):
        callback.on_tool_start({"name": "approve_refund"}, "{}", metadata="bad")
