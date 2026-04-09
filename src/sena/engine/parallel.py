from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sena.core.models import EvaluatorConfig, PolicyBundleMetadata, PolicyRule
from sena.engine.replay import ReplayCase, evaluate_replay_cases


@dataclass(frozen=True)
class ParallelRunDiscrepancy:
    case_id: str
    old_outcome: str
    new_outcome: str
    old_matched_controls: list[str]
    new_matched_controls: list[str]
    old_missing_evidence: list[str]
    new_missing_evidence: list[str]
    outcome_changed: bool
    controls_changed: bool
    missing_evidence_changed: bool
    source_system: str
    workflow_stage: str
    risk_category: str



def run_parallel_mode(
    *,
    cases: list[ReplayCase],
    old_rules: list[PolicyRule],
    old_metadata: PolicyBundleMetadata,
    new_rules: list[PolicyRule],
    new_metadata: PolicyBundleMetadata,
    config: EvaluatorConfig | None = None,
) -> dict[str, Any]:
    old_results = evaluate_replay_cases(
        cases=cases,
        rules=old_rules,
        metadata=old_metadata,
        config=config,
    )
    new_results = evaluate_replay_cases(
        cases=cases,
        rules=new_rules,
        metadata=new_metadata,
        config=config,
    )

    discrepancies: list[ParallelRunDiscrepancy] = []
    for case in cases:
        old = old_results[case.case_id]
        new = new_results[case.case_id]
        discrepancies.append(
            ParallelRunDiscrepancy(
                case_id=case.case_id,
                old_outcome=old.outcome,
                new_outcome=new.outcome,
                old_matched_controls=old.matched_controls,
                new_matched_controls=new.matched_controls,
                old_missing_evidence=old.missing_evidence,
                new_missing_evidence=new.missing_evidence,
                outcome_changed=old.outcome != new.outcome,
                controls_changed=old.matched_controls != new.matched_controls,
                missing_evidence_changed=old.missing_evidence != new.missing_evidence,
                source_system=case.source_system,
                workflow_stage=case.workflow_stage,
                risk_category=case.risk_category,
            )
        )

    outcome_changes = [item for item in discrepancies if item.outcome_changed]
    control_changes = [item for item in discrepancies if item.controls_changed]
    evidence_changes = [item for item in discrepancies if item.missing_evidence_changed]
    total = len(discrepancies)
    old_escalations = sum(1 for item in old_results.values() if item.escalation)
    new_escalations = sum(1 for item in new_results.values() if item.escalation)

    return {
        "report_type": "sena.parallel_run_discrepancy_report",
        "mode": "parallel",
        "old_label": f"{old_metadata.bundle_name}:{old_metadata.version}",
        "new_label": f"{new_metadata.bundle_name}:{new_metadata.version}",
        "total_cases": total,
        "discrepancy_summary": {
            "outcome_changes": len(outcome_changes),
            "matched_control_changes": len(control_changes),
            "missing_evidence_changes": len(evidence_changes),
        },
        "escalation_rates": {
            "old": 0.0 if total == 0 else old_escalations / total,
            "new": 0.0 if total == 0 else new_escalations / total,
            "delta": 0.0 if total == 0 else (new_escalations - old_escalations) / total,
        },
        "discrepancies": [item.__dict__ for item in discrepancies],
    }
