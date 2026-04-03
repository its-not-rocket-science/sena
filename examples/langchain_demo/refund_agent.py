"""LangChain demo: SENA blocks refunds > $100 without manager approval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sena.integrations.langchain import SenaApprovalCallback, SenaBlockedError


@dataclass(frozen=True)
class DemoTool:
    name: str


def run_demo() -> list[dict[str, Any]]:
    callback = SenaApprovalCallback(
        sena_endpoint="http://localhost:8000",
        policy_bundle="enterprise-demo:active",
    )

    scripted_calls = [
        {
            "tool": DemoTool(name="approve_refund"),
            "input": '{"amount": 25, "currency": "USD", "manager_approved": false}',
            "metadata": {},
        },
        {
            "tool": DemoTool(name="approve_refund"),
            "input": '{"amount": 250, "currency": "USD", "manager_approved": false}',
            "metadata": {},
        },
    ]

    decisions: list[dict[str, Any]] = []
    for index, call in enumerate(scripted_calls, start=1):
        metadata = call["metadata"]
        try:
            callback.on_tool_start(
                {"name": call["tool"].name},
                call["input"],
                run_id=f"refund-run-{index}",
                metadata=metadata,
            )
            decisions.append(
                {
                    "run_id": f"refund-run-{index}",
                    "outcome": "APPROVED",
                    "decision_id": metadata.get("sena_decision_id"),
                    "proof": metadata.get("sena_proof", []),
                }
            )
            print(
                "APPROVED",
                f"run={index}",
                f"decision_id={metadata.get('sena_decision_id')}",
                f"proof={metadata.get('sena_proof', [])}",
            )
        except SenaBlockedError as exc:
            decisions.append(
                {
                    "run_id": f"refund-run-{index}",
                    "outcome": "BLOCKED",
                    "reason": str(exc),
                    "decision_id": metadata.get("sena_decision_id"),
                    "proof": metadata.get("sena_proof", []),
                }
            )
            print("BLOCKED", f"run={index}", str(exc))
    return decisions


if __name__ == "__main__":
    run_demo()
