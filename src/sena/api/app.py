from __future__ import annotations

from pathlib import Path

from sena.core.models import ActionProposal
from sena.engine.evaluator import PolicyEvaluator
from sena.policy.parser import load_policies_from_dir

try:
    from fastapi import FastAPI
except ModuleNotFoundError:  # pragma: no cover
    FastAPI = None  # type: ignore


def create_app(policy_dir: str | None = None):
    if FastAPI is None:
        raise RuntimeError("FastAPI is not installed. Install optional API dependencies first.")

    app = FastAPI(title="SENA Compliance Engine", version="0.2.0")
    resolved_policy_dir = policy_dir or str(
        Path(__file__).resolve().parents[1] / "examples" / "policies"
    )
    evaluator = PolicyEvaluator(load_policies_from_dir(resolved_policy_dir))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/evaluate")
    def evaluate(req: dict):
        proposal = ActionProposal(
            action_type=req["action_type"],
            request_id=req.get("request_id"),
            actor_id=req.get("actor_id"),
            attributes=req.get("attributes", {}),
        )
        trace = evaluator.evaluate(proposal, req.get("facts", {}))
        return trace.to_dict()

    return app


app = create_app() if FastAPI is not None else None
