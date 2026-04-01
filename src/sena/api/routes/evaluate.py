from __future__ import annotations

from fastapi import APIRouter, Request

from sena.api.errors import raise_api_error
from sena.api.runtime import EngineState, parse_default_decision
from sena.api.schemas import BatchEvaluateRequest, EvaluateRequest, SimulationRequest
from sena.core.models import ActionProposal, EvaluatorConfig
from sena.engine.evaluator import PolicyEvaluator
from sena.engine.review_package import build_decision_review_package
from sena.engine.simulation import SimulationScenario, simulate_bundle_impact
from sena.integrations.base import DecisionPayload
from sena.policy.parser import load_policy_bundle


def create_evaluate_router(state: EngineState) -> APIRouter:
    router = APIRouter()

    def _evaluate(req: EvaluateRequest, request: Request) -> dict:
        try:
            def _notify_slack(trace) -> None:
                if state.slack_client is None:
                    return
                state.slack_client.send_decision(
                    DecisionPayload(
                        decision_id=trace.decision_id,
                        request_id=trace.request_id,
                        action_type=trace.action_type,
                        matched_rule_ids=[item.rule_id for item in trace.matched_rules],
                        summary=trace.summary,
                    )
                )

            proposal = ActionProposal(
                action_type=req.action_type,
                request_id=req.request_id or request.state.request_id,
                actor_id=req.actor_id,
                actor_role=req.actor_role,
                attributes=req.attributes,
            )
            evaluator = PolicyEvaluator(
                state.rules,
                policy_bundle=state.metadata,
                config=EvaluatorConfig(
                    default_decision=parse_default_decision(req.default_decision),
                    require_allow_match=req.strict_require_allow,
                    on_escalation=_notify_slack,
                ),
            )
            with state.metrics.evaluation_timer(endpoint="/v1/evaluate"):
                trace = evaluator.evaluate(proposal, req.facts)
            state.metrics.observe_decision_outcome(endpoint="/v1/evaluate", outcome=trace.outcome.value)
            payload = trace.to_dict()
            if state.settings.audit_sink_jsonl:
                from sena.audit.chain import append_audit_record

                payload["audit_record"] = append_audit_record(
                    state.settings.audit_sink_jsonl, payload["audit_record"]
                )
            return payload
        except Exception as exc:  # pragma: no cover
            raise_api_error("evaluation_error", details={"reason": str(exc)})

    @router.post("/evaluate")
    def evaluate(req: EvaluateRequest, request: Request) -> dict:
        return _evaluate(req, request)

    @router.post("/evaluate/review-package")
    def evaluate_review_package(req: EvaluateRequest, request: Request) -> dict:
        try:
            proposal = ActionProposal(
                action_type=req.action_type,
                request_id=req.request_id or request.state.request_id,
                actor_id=req.actor_id,
                actor_role=req.actor_role,
                attributes=req.attributes,
            )
            evaluator = PolicyEvaluator(
                state.rules,
                policy_bundle=state.metadata,
                config=EvaluatorConfig(
                    default_decision=parse_default_decision(req.default_decision),
                    require_allow_match=req.strict_require_allow,
                ),
            )
            with state.metrics.evaluation_timer(endpoint="/v1/evaluate/review-package"):
                trace = evaluator.evaluate(proposal, req.facts)
            state.metrics.observe_decision_outcome(
                endpoint="/v1/evaluate/review-package",
                outcome=trace.outcome.value,
            )
            return build_decision_review_package(trace)
        except Exception as exc:  # pragma: no cover
            raise_api_error("evaluation_error", details={"reason": str(exc)})

    @router.post("/evaluate/batch")
    def evaluate_batch(req: BatchEvaluateRequest, request: Request) -> dict:
        return {"count": len(req.items), "results": [_evaluate(item, request) for item in req.items]}

    @router.post("/simulation")
    def simulation(req: SimulationRequest) -> dict:
        baseline_rules, baseline_meta = load_policy_bundle(req.baseline_policy_dir)
        candidate_rules, candidate_meta = load_policy_bundle(req.candidate_policy_dir)
        scenarios = {
            item.scenario_id: SimulationScenario(
                action_type=item.action_type,
                request_id=item.request_id,
                actor_id=item.actor_id,
                attributes=item.attributes,
                facts=item.facts,
                source_system=item.source_system,
                workflow_stage=item.workflow_stage,
                risk_category=item.risk_category,
            )
            for item in req.scenarios
        }
        return simulate_bundle_impact(
            scenarios, baseline_rules, candidate_rules, baseline_meta, candidate_meta
        )

    return router
