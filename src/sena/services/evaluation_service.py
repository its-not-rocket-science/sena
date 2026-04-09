from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any

from sena.api.logging import get_logger
from sena.core.enums import ActionOrigin
from sena.core.models import (
    AIActionMetadata,
    ActionProposal,
    AutonomousToolMetadata,
    EvaluatorConfig,
    RiskClassification,
)
from sena.engine.evaluator import PolicyEvaluator
from sena.engine.replay import (
    build_drift_report,
    evaluate_replay_cases,
    load_replay_cases,
)
from sena.engine.review_package import build_decision_review_package
from sena.engine.simulation import SimulationScenario, simulate_bundle_impact
from sena.integrations.base import DecisionPayload
from sena.audit.sinks import JsonlFileAuditSink
from sena.policy.parser import load_policy_bundle
from sena.services.audit_service import AuditService

logger = get_logger(__name__)


@dataclass
class EvaluationService:
    state: Any
    audit_service: AuditService

    @staticmethod
    def build_action_proposal(
        *,
        action_type: str,
        request_id: str,
        actor_id: str | None,
        actor_role: str | None,
        attributes: dict[str, Any],
        action_origin: ActionOrigin = ActionOrigin.HUMAN,
        ai_metadata: dict[str, Any] | None = None,
        autonomous_metadata: dict[str, Any] | None = None,
    ) -> ActionProposal:
        normalized_ai_metadata = None
        if ai_metadata is not None:
            risk = ai_metadata.get("risk_classification")
            normalized_ai_metadata = AIActionMetadata(
                originating_system=ai_metadata["originating_system"],
                originating_model=ai_metadata.get("originating_model"),
                prompt_context_ref=ai_metadata.get("prompt_context_ref"),
                confidence=ai_metadata.get("confidence"),
                uncertainty=ai_metadata.get("uncertainty"),
                requested_tool=ai_metadata.get("requested_tool"),
                requested_action=ai_metadata.get("requested_action"),
                evidence_references=list(ai_metadata.get("evidence_references", [])),
                citation_references=list(ai_metadata.get("citation_references", [])),
                human_requester=ai_metadata.get("human_requester"),
                human_owner=ai_metadata.get("human_owner"),
                human_approver=ai_metadata.get("human_approver"),
                risk_classification=RiskClassification(**risk) if risk else None,
            )
        normalized_autonomous_metadata = None
        if autonomous_metadata is not None:
            normalized_autonomous_metadata = AutonomousToolMetadata(
                **autonomous_metadata
            )
        return ActionProposal(
            action_type=action_type,
            request_id=request_id,
            actor_id=actor_id,
            actor_role=actor_role,
            attributes=attributes,
            action_origin=action_origin,
            ai_metadata=normalized_ai_metadata,
            autonomous_metadata=normalized_autonomous_metadata,
        )

    def _notify_slack(self, trace: Any) -> None:
        if self.state.slack_client is None:
            return
        self.state.slack_client.send_decision(
            DecisionPayload(
                decision_id=trace.decision_id,
                request_id=trace.request_id,
                action_type=trace.action_type,
                matched_rule_ids=[item.rule_id for item in trace.matched_rules],
                summary=trace.summary,
            )
        )

    def evaluate(
        self,
        *,
        proposal: ActionProposal,
        facts: dict[str, Any],
        endpoint: str,
        default_decision: Any,
        strict_require_allow: bool,
        notify_on_escalation: bool = True,
        append_audit: bool = True,
        replay_input: dict[str, Any] | None = None,
        simulate_exceptions: bool = False,
    ) -> dict[str, Any]:
        active_exceptions = self.state.exception_service.list_active()
        evaluator = PolicyEvaluator(
            self.state.rules,
            exceptions=active_exceptions,
            policy_bundle=self.state.metadata,
            config=EvaluatorConfig(
                default_decision=default_decision,
                require_allow_match=strict_require_allow,
                on_escalation=self._notify_slack if notify_on_escalation else None,
            ),
        )
        started = perf_counter()
        with self.state.metrics.evaluation_timer():
            trace = evaluator.evaluate(proposal, facts)
        evaluation_ms = round((perf_counter() - started) * 1000, 3)
        policy_bundle = f"{self.state.metadata.bundle_name}:{self.state.metadata.version}"
        self.state.metrics.observe_decision_outcome(
            outcome=trace.outcome.value,
            policy=policy_bundle,
        )
        logger.info(
            "decision_evaluated",
            decision_id=trace.decision_id,
            outcome=trace.outcome.value,
            policy_bundle=policy_bundle,
            evaluation_ms=evaluation_ms,
            endpoint=endpoint,
        )
        payload = trace.to_dict()
        if simulate_exceptions:
            baseline_trace = PolicyEvaluator(
                self.state.rules,
                exceptions=[],
                policy_bundle=self.state.metadata,
                config=EvaluatorConfig(
                    default_decision=default_decision,
                    require_allow_match=strict_require_allow,
                    on_escalation=None,
                ),
            ).evaluate(proposal, facts)
            payload["exception_simulation"] = {
                "without_exceptions": {
                    "outcome": baseline_trace.outcome.value,
                    "decision_hash": baseline_trace.decision_hash,
                },
                "with_exceptions": {
                    "outcome": trace.outcome.value,
                    "decision_hash": trace.decision_hash,
                },
                "changed": baseline_trace.outcome != trace.outcome,
            }
        if replay_input is not None and "audit_record" in payload:
            payload["audit_record"]["replay_input"] = replay_input
        if append_audit:
            appended = self.audit_service.append_record(payload["audit_record"])
            if appended is not None:
                payload["audit_record"] = appended
                self.state.metrics.observe_audit_write(
                    write_timestamp=appended.get("write_timestamp")
                )
        return payload

    def evaluate_review_package(
        self,
        *,
        proposal: ActionProposal,
        facts: dict[str, Any],
        endpoint: str,
        default_decision: Any,
        strict_require_allow: bool,
    ) -> dict[str, Any]:
        evaluator = PolicyEvaluator(
            self.state.rules,
            exceptions=self.state.exception_service.list_active(),
            policy_bundle=self.state.metadata,
            config=EvaluatorConfig(
                default_decision=default_decision,
                require_allow_match=strict_require_allow,
            ),
        )
        started = perf_counter()
        with self.state.metrics.evaluation_timer():
            trace = evaluator.evaluate(proposal, facts)
        evaluation_ms = round((perf_counter() - started) * 1000, 3)
        policy_bundle = f"{self.state.metadata.bundle_name}:{self.state.metadata.version}"
        self.state.metrics.observe_decision_outcome(
            outcome=trace.outcome.value,
            policy=policy_bundle,
        )
        logger.info(
            "decision_evaluated",
            decision_id=trace.decision_id,
            outcome=trace.outcome.value,
            policy_bundle=policy_bundle,
            evaluation_ms=evaluation_ms,
            endpoint=endpoint,
        )
        return build_decision_review_package(trace)

    @staticmethod
    def simulate_policy_change(
        *,
        baseline_policy_dir: str,
        candidate_policy_dir: str,
        scenarios: list[dict[str, Any]],
    ) -> dict[str, Any]:
        baseline_rules, baseline_meta = load_policy_bundle(baseline_policy_dir)
        candidate_rules, candidate_meta = load_policy_bundle(candidate_policy_dir)
        scenario_map = {
            item["scenario_id"]: SimulationScenario(
                action_type=item["action_type"],
                request_id=item["request_id"],
                actor_id=item.get("actor_id"),
                attributes=item.get("attributes", {}),
                facts=item["facts"],
                source_system=item.get("source_system", "api"),
                workflow_stage=item.get("workflow_stage"),
                risk_category=item.get("risk_category"),
            )
            for item in scenarios
        }
        return simulate_bundle_impact(
            scenario_map,
            baseline_rules,
            candidate_rules,
            baseline_meta,
            candidate_meta,
        )

    @staticmethod
    def replay_policy_drift(
        *,
        replay_payload: dict[str, Any],
        baseline_policy_dir: str,
        candidate_policy_dir: str | None = None,
        baseline_mapping_mode: str | None = None,
        baseline_mapping_config_path: str | None = None,
        candidate_mapping_mode: str | None = None,
        candidate_mapping_config_path: str | None = None,
    ) -> dict[str, Any]:
        baseline_rules, baseline_meta = load_policy_bundle(baseline_policy_dir)
        candidate_rules = baseline_rules
        candidate_meta = baseline_meta
        if candidate_policy_dir is not None:
            candidate_rules, candidate_meta = load_policy_bundle(candidate_policy_dir)

        baseline_cases = load_replay_cases(
            replay_payload,
            mapping_mode=baseline_mapping_mode,
            mapping_config_path=baseline_mapping_config_path,
        )
        candidate_cases = load_replay_cases(
            replay_payload,
            mapping_mode=candidate_mapping_mode or baseline_mapping_mode,
            mapping_config_path=candidate_mapping_config_path
            or baseline_mapping_config_path,
        )
        baseline_result = evaluate_replay_cases(
            cases=baseline_cases, rules=baseline_rules, metadata=baseline_meta
        )
        candidate_result = evaluate_replay_cases(
            cases=candidate_cases, rules=candidate_rules, metadata=candidate_meta
        )
        return build_drift_report(
            cases=baseline_cases,
            baseline=baseline_result,
            candidate=candidate_result,
            baseline_label=f"{baseline_meta.bundle_name}:{baseline_meta.version}",
            candidate_label=f"{candidate_meta.bundle_name}:{candidate_meta.version}",
        )

    @staticmethod
    def replay_recent_traffic(
        *,
        audit_path: str | None,
        proposed_policy_dir: str,
        window_seconds: int,
        max_samples: int,
    ) -> dict[str, Any]:
        if not audit_path:
            raise ValueError("audit sink not configured")
        sink = JsonlFileAuditSink(path=audit_path)
        records = sink.load_records()
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
        candidate_rules, candidate_meta = load_policy_bundle(proposed_policy_dir)
        evaluator = PolicyEvaluator(candidate_rules, policy_bundle=candidate_meta)

        changed = 0
        unchanged = 0
        replayed = 0
        skipped = 0
        samples: list[dict[str, Any]] = []
        for row in records:
            replay_input = row.get("replay_input")
            ts_raw = row.get("write_timestamp") or row.get("timestamp")
            if not isinstance(ts_raw, str):
                skipped += 1
                continue
            try:
                timestamp = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except ValueError:
                skipped += 1
                continue
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            if timestamp < cutoff:
                continue
            if not isinstance(replay_input, dict):
                skipped += 1
                continue
            action_type = replay_input.get("action_type")
            if not isinstance(action_type, str) or not action_type:
                skipped += 1
                continue
            proposal = ActionProposal(
                action_type=action_type,
                request_id=replay_input.get("request_id"),
                actor_id=replay_input.get("actor_id"),
                actor_role=replay_input.get("actor_role"),
                attributes=dict(replay_input.get("attributes") or {}),
            )
            facts = replay_input.get("facts") or {}
            if not isinstance(facts, dict):
                skipped += 1
                continue
            trace = evaluator.evaluate(proposal, facts)
            replayed += 1
            before = str(row.get("outcome", "UNKNOWN"))
            after = trace.outcome.value
            if before != after:
                changed += 1
                if len(samples) < max_samples:
                    samples.append(
                        {
                            "decision_id": row.get("decision_id"),
                            "action_type": action_type,
                            "before": before,
                            "after": after,
                        }
                    )
            else:
                unchanged += 1
        return {
            "window_seconds": window_seconds,
            "proposed_bundle": {
                "bundle_name": candidate_meta.bundle_name,
                "version": candidate_meta.version,
            },
            "summary": f"{changed} events would change outcome, {unchanged} would stay same",
            "total_replayed": replayed,
            "changed_outcomes": changed,
            "unchanged_outcomes": unchanged,
            "skipped_events": skipped,
            "changed_samples": samples,
        }
