from __future__ import annotations

from pathlib import Path

from sena.api.schemas import EvaluateRequest, HealthResponse
from sena.core.enums import DecisionOutcome
from sena.core.models import ActionProposal, EvaluatorConfig
from sena.engine.evaluator import PolicyEvaluator
from sena.policy.parser import PolicyParseError, load_policy_bundle

try:
    from fastapi import FastAPI, HTTPException
except ModuleNotFoundError:  # pragma: no cover
    FastAPI = None  # type: ignore


def create_app(
    policy_dir: str | None = None,
    bundle_name: str = "default-bundle",
    bundle_version: str = "0.1.0-alpha",
):
    if FastAPI is None:
        raise RuntimeError("FastAPI is not installed. Install optional API dependencies first.")

    resolved_policy_dir = policy_dir or str(
        Path(__file__).resolve().parents[1] / "examples" / "policies"
    )

    try:
        rules, metadata = load_policy_bundle(
            resolved_policy_dir,
            bundle_name=bundle_name,
            version=bundle_version,
        )
    except PolicyParseError as exc:
        raise RuntimeError(f"Failed to load policy bundle: {exc}") from exc

    app = FastAPI(title="SENA Compliance Engine API", version="0.2.0")

    def _parse_default_decision(raw: str) -> DecisionOutcome:
        if raw == "ESCALATE":
            return DecisionOutcome.ESCALATE_FOR_HUMAN_REVIEW
        return DecisionOutcome(raw)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", bundle=metadata)

    @app.get("/bundle")
    def bundle() -> dict[str, str]:
        return {
            "bundle_name": metadata.bundle_name,
            "version": metadata.version,
            "loaded_from": metadata.loaded_from,
        }

    @app.post("/evaluate")
    def evaluate(req: EvaluateRequest) -> dict:
        try:
            proposal = ActionProposal(
                action_type=req.action_type,
                request_id=req.request_id,
                actor_id=req.actor_id,
                attributes=req.attributes,
            )
            evaluator = PolicyEvaluator(
                rules,
                policy_bundle=metadata,
                config=EvaluatorConfig(
                    default_decision=_parse_default_decision(req.default_decision),
                    require_allow_match=req.strict_require_allow,
                ),
            )
            trace = evaluator.evaluate(proposal, req.facts)
            return trace.to_dict()
        except Exception as exc:  # pragma: no cover
            raise HTTPException(status_code=400, detail=f"Evaluation error: {exc}") from exc

    return app


app = create_app() if FastAPI is not None else None
