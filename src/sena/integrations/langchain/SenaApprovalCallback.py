from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Protocol
from urllib import request
from urllib.error import HTTPError, URLError

from sena.integrations.base import IntegrationError

try:  # pragma: no cover - optional dependency
    from langchain.callbacks.base import BaseCallbackHandler
except ModuleNotFoundError:  # pragma: no cover
    class BaseCallbackHandler:  # type: ignore[no-redef]
        pass


class ToolLike(Protocol):
    name: str


class LangChainIntegrationError(IntegrationError):
    """Raised when the LangChain callback cannot deterministically evaluate a tool call."""


class SenaBlockedError(LangChainIntegrationError):
    """Raised when SENA blocks a tool invocation."""


@dataclass(frozen=True)
class SenaDecision:
    outcome: str
    evidence: str
    decision_id: str
    merkle_proof: list[str]


class SenaClient:
    """Minimal HTTP client for SENA's evaluate endpoint."""

    def __init__(self, endpoint: str, *, timeout_seconds: int = 10):
        normalized = endpoint.strip().rstrip("/")
        if not normalized:
            raise LangChainIntegrationError("SENA endpoint must be non-empty")
        self._evaluate_url = f"{normalized}/v1/evaluate"
        self._timeout_seconds = timeout_seconds

    def evaluate(self, payload: dict[str, Any]) -> SenaDecision:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            self._evaluate_url,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self._timeout_seconds) as resp:  # nosec: B310
                response_payload = json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            raise LangChainIntegrationError(
                f"SENA API HTTP error during evaluate: {exc.code}"
            ) from exc
        except URLError as exc:
            raise LangChainIntegrationError(
                f"SENA API connectivity error during evaluate: {exc.reason}"
            ) from exc

        outcome = str(response_payload.get("outcome") or "").strip()
        if not outcome:
            raise LangChainIntegrationError("SENA API response missing outcome")

        decision_id = str(response_payload.get("decision_id") or "").strip()
        if not decision_id:
            raise LangChainIntegrationError("SENA API response missing decision_id")

        audit_record = response_payload.get("audit_record")
        merkle_proof: list[str] = []
        if isinstance(audit_record, dict):
            proof_candidate = audit_record.get("merkle_proof")
            if isinstance(proof_candidate, list):
                merkle_proof = [str(item) for item in proof_candidate]

        evidence = str(response_payload.get("summary") or "")
        return SenaDecision(
            outcome=outcome,
            evidence=evidence,
            decision_id=decision_id,
            merkle_proof=merkle_proof,
        )


class SenaApprovalCallback(BaseCallbackHandler):
    def __init__(
        self,
        sena_endpoint: str,
        policy_bundle: str,
        *,
        sena_client: SenaClient | None = None,
    ):
        cleaned_bundle = policy_bundle.strip()
        if not cleaned_bundle:
            raise LangChainIntegrationError("policy_bundle must be non-empty")
        self.sena = sena_client or SenaClient(sena_endpoint)
        self.policy_bundle = cleaned_bundle

    def on_tool_start(self, serialized: dict[str, Any], input_str: str, **kwargs) -> None:
        tool_name = str(serialized.get("name") or "").strip()
        if not tool_name:
            raise LangChainIntegrationError("LangChain tool payload missing tool name")

        run_id = str(kwargs.get("run_id") or uuid.uuid4())
        decision = self.sena.evaluate(
            {
                "action_type": tool_name,
                "request_id": run_id,
                "action_origin": "autonomous_tool",
                "autonomous_metadata": {
                    "tool_name": tool_name,
                    "trigger_type": "langchain_tool_start",
                    "trigger_reference": run_id,
                },
                "attributes": {
                    "input": input_str,
                    "agent_context": run_id,
                    "policy_bundle": self.policy_bundle,
                },
            }
        )

        if decision.outcome == "BLOCKED":
            raise SenaBlockedError(f"Blocked: {decision.evidence}")

        metadata = kwargs.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            raise LangChainIntegrationError(
                "LangChain callback metadata must be a dictionary"
            )
        metadata["sena_decision_id"] = decision.decision_id
        metadata["sena_proof"] = decision.merkle_proof
