from __future__ import annotations

import logging
import json
from dataclasses import dataclass
from typing import Any, Callable

from sena.api.schemas import BundleInfo, BundlePromoteRequest, BundleRegisterRequest, BundleRollbackRequest
from sena.engine.simulation import SimulationScenario, simulate_bundle_impact
from sena.policy.lifecycle import PromotionGatePolicy, diff_rule_sets, evaluate_promotion_gate, validate_promotion
from sena.policy.parser import load_policy_bundle
from sena.policy.store import PolicyStoreError

logger = logging.getLogger(__name__)


@dataclass
class BundleService:
    policy_repo: Any | None
    settings: Any
    state: Any
    verify_signature: Callable[..., tuple[bool, list[str], str]]

    def register_bundle(self, payload: BundleRegisterRequest) -> dict[str, Any]:
        policy_dir = payload.policy_dir or self.settings.policy_dir
        rules, metadata = load_policy_bundle(
            policy_dir,
            bundle_name=payload.bundle_name or self.settings.bundle_name,
            version=payload.bundle_version or self.settings.bundle_version,
        )
        metadata.lifecycle = payload.lifecycle
        signature_ok, signature_errors, manifest_path = self.verify_signature(
            policy_dir=policy_dir,
            manifest_filename=self.settings.bundle_release_manifest_filename,
            keyring_dir=self.settings.bundle_signature_keyring_dir,
            strict=self.settings.bundle_signature_strict,
        )
        if self.settings.bundle_signature_strict and not signature_ok:
            raise PermissionError("bundle_signature_verification_failed:" + "; ".join(signature_errors))
        bundle_id = self.policy_repo.register_bundle(
            metadata,
            rules,
            created_by=payload.created_by,
            creation_reason=payload.creation_reason,
            source_bundle_id=payload.source_bundle_id,
            compatibility_notes=payload.compatibility_notes,
            release_notes=payload.release_notes,
            migration_notes=payload.migration_notes,
            release_manifest_path=manifest_path,
            signature_verification_strict=self.settings.bundle_signature_strict,
            signature_verified=signature_ok,
            signature_error="; ".join(signature_errors) if signature_errors else None,
        )
        return {
            "bundle_id": bundle_id,
            "bundle": metadata.__dict__,
            "rules_total": len(rules),
            "signature": {"verified": signature_ok, "errors": signature_errors},
        }

    def promote_bundle(self, payload: BundlePromoteRequest) -> dict[str, Any]:
        stored_bundle = self.policy_repo.get_bundle(payload.bundle_id)
        if stored_bundle is None:
            raise ValueError("bundle_not_found")
        if stored_bundle.metadata.lifecycle == payload.target_lifecycle:
            return {
                "status": "ok",
                "bundle_id": payload.bundle_id,
                "lifecycle": payload.target_lifecycle,
                "idempotent": True,
            }
        source_rules = stored_bundle.rules
        current_active = None
        if payload.target_lifecycle == "active":
            current_active = self.policy_repo.get_active_bundle(stored_bundle.metadata.bundle_name)
            source_rules = current_active.rules if current_active is not None else []
        source_metadata = current_active.metadata if (payload.target_lifecycle == "active" and current_active is not None) else stored_bundle.metadata

        policy_diff = diff_rule_sets(source_rules, stored_bundle.rules).__dict__
        simulation_report: dict[str, Any] | None = payload.simulation_result
        if payload.target_lifecycle == "active" and simulation_report is None and payload.simulation_scenarios:
            scenarios = {
                scenario.scenario_id: SimulationScenario(
                    action_type=scenario.action_type,
                    request_id=scenario.request_id,
                    actor_id=scenario.actor_id,
                    attributes=scenario.attributes,
                    facts=scenario.facts,
                    source_system=scenario.source_system,
                    workflow_stage=scenario.workflow_stage,
                    risk_category=scenario.risk_category,
                )
                for scenario in payload.simulation_scenarios
            }
            simulation_report = simulate_bundle_impact(
                scenarios,
                source_rules,
                stored_bundle.rules,
                source_metadata,
                stored_bundle.metadata,
            )

        threshold_errors = self._evaluate_thresholds(simulation_report, payload.thresholds)
        gate_failures = evaluate_promotion_gate(
            target_lifecycle=payload.target_lifecycle,
            validation_artifact=payload.validation_artifact,
            simulation_report=simulation_report,
            break_glass=payload.break_glass,
            break_glass_reason=payload.break_glass_reason,
            policy=self._effective_gate_policy(payload.thresholds),
        )

        validation = validate_promotion(
            stored_bundle.metadata.lifecycle,
            payload.target_lifecycle,
            source_rules,
            stored_bundle.rules,
            validation_artifact=payload.validation_artifact,
            signature_verified=stored_bundle.signature_verified,
            signature_verification_strict=stored_bundle.signature_verification_strict,
        )
        errors = [*validation.errors, *threshold_errors, *[item.message for item in gate_failures]]
        requires_block = (not payload.break_glass) or any(
            item.code in {"break_glass_reason_required", "break_glass_disabled"} for item in gate_failures
        )
        if errors and requires_block:
            raise RuntimeError(
                "promotion_validation_failed:"
                + json.dumps(
                    {
                        "messages": errors,
                        "failures": [item.__dict__ for item in gate_failures],
                    },
                    sort_keys=True,
                )
            )

        try:
            self.policy_repo.transition_bundle(
                payload.bundle_id,
                payload.target_lifecycle,
                promoted_by=payload.promoted_by,
                promotion_reason=payload.promotion_reason if not payload.break_glass else f"[BREAK_GLASS] {payload.promotion_reason}",
                validation_artifact=payload.validation_artifact,
                policy_diff_summary=json.dumps(policy_diff, sort_keys=True),
                evidence_json=json.dumps(
                    {
                        "simulation_report": simulation_report,
                        "thresholds": payload.thresholds.model_dump() if payload.thresholds else {},
                        "threshold_errors": threshold_errors,
                        "promotion_gate_failures": [item.__dict__ for item in gate_failures],
                        "break_glass_reason": payload.break_glass_reason,
                    },
                    sort_keys=True,
                ),
                break_glass=payload.break_glass,
                audit_marker="break_glass_promotion" if payload.break_glass else "promotion",
                action="promote_break_glass" if payload.break_glass else "promote",
            )
        except PolicyStoreError as exc:
            raise RuntimeError(str(exc)) from exc
        active = self.policy_repo.get_active_bundle(self.settings.bundle_name)
        if active is not None:
            self.state.rules = active.rules
            self.state.metadata = active.metadata
        return {"status": "ok", "bundle_id": payload.bundle_id, "lifecycle": payload.target_lifecycle}

    def _effective_gate_policy(
        self,
        thresholds: BundlePromoteRequest.PromotionThresholds | None,
    ) -> PromotionGatePolicy:
        combined_regressions = dict(self.settings.promotion_gate_max_regressions_by_outcome_type)
        if thresholds and thresholds.max_block_to_approve_regressions is not None:
            combined_regressions["BLOCKED->APPROVED"] = thresholds.max_block_to_approve_regressions
        if thresholds:
            combined_regressions.update(thresholds.max_regressions_by_outcome_type)
        return PromotionGatePolicy(
            require_validation_artifact=self.settings.promotion_gate_require_validation_artifact,
            require_simulation=self.settings.promotion_gate_require_simulation,
            required_scenario_ids=self.settings.promotion_gate_required_scenario_ids,
            max_changed_outcomes=(
                thresholds.max_changed_outcomes
                if thresholds and thresholds.max_changed_outcomes is not None
                else self.settings.promotion_gate_max_changed_outcomes
            ),
            max_regressions_by_outcome_type=combined_regressions,
            break_glass_enabled=self.settings.promotion_gate_break_glass_enabled,
        )

    def _evaluate_thresholds(
        self,
        simulation_report: dict[str, Any] | None,
        thresholds: BundlePromoteRequest.PromotionThresholds | None,
    ) -> list[str]:
        if simulation_report is None or thresholds is None:
            return []
        errors: list[str] = []
        changed_scenarios = int(simulation_report.get("changed_scenarios", 0))
        if thresholds.max_changed_outcomes is not None and changed_scenarios > thresholds.max_changed_outcomes:
            errors.append(
                f"changed outcomes {changed_scenarios} exceeds threshold {thresholds.max_changed_outcomes}"
            )
        block_to_approve = sum(
            1
            for item in simulation_report.get("changes", [])
            if item.get("before_outcome") == "BLOCKED" and item.get("after_outcome") == "APPROVED"
        )
        if (
            thresholds.max_block_to_approve_regressions is not None
            and block_to_approve > thresholds.max_block_to_approve_regressions
        ):
            errors.append(
                "block->approve regressions "
                f"{block_to_approve} exceeds threshold {thresholds.max_block_to_approve_regressions}"
            )
        risk_changes = simulation_report.get("grouped_changes", {}).get("risk_category", {})
        for risk_category, max_changed in thresholds.max_changed_risk_categories.items():
            observed = int(risk_changes.get(risk_category, {}).get("changed", 0))
            if observed > max_changed:
                errors.append(
                    f"risk category '{risk_category}' changed outcomes {observed} exceeds threshold {max_changed}"
                )
        covered_categories = set(risk_changes.keys())
        required = {item for item in thresholds.required_risk_categories if item}
        missing = sorted(required - covered_categories)
        if (
            thresholds.max_missing_scenario_coverage is not None
            and len(missing) > thresholds.max_missing_scenario_coverage
        ):
            errors.append(
                "missing scenario coverage "
                f"{len(missing)} exceeds threshold {thresholds.max_missing_scenario_coverage}: {missing}"
            )
        return errors

    def rollback_bundle(self, payload: BundleRollbackRequest) -> dict[str, Any]:
        try:
            self.policy_repo.rollback_bundle(
                payload.bundle_name,
                payload.to_bundle_id,
                promoted_by=payload.promoted_by,
                promotion_reason=payload.promotion_reason,
                validation_artifact=payload.validation_artifact,
            )
        except PolicyStoreError as exc:
            raise ValueError(str(exc)) from exc
        active = self.policy_repo.get_active_bundle(payload.bundle_name)
        if active is not None and payload.bundle_name == self.settings.bundle_name:
            self.state.rules = active.rules
            self.state.metadata = active.metadata
        return {"status": "ok", "bundle_name": payload.bundle_name, "active_bundle_id": payload.to_bundle_id}

    def get_active_bundle(self, bundle_name: str | None = None) -> dict[str, Any] | None:
        name = bundle_name or self.settings.bundle_name
        active = self.policy_repo.get_active_bundle(name)
        if active is None:
            return None
        return {
            "bundle_id": active.id,
            "bundle": BundleInfo.model_validate(active.metadata.__dict__),
            "release_id": active.release_id,
            "created_by": active.created_by,
            "promoted_by": active.promoted_by,
            "promotion_reason": active.promotion_reason,
            "validation_artifact": active.validation_artifact,
            "source_bundle_id": active.source_bundle_id,
            "integrity_digest": active.integrity_digest,
            "release_notes": active.release_notes,
            "migration_notes": active.migration_notes,
            "rules_total": len(active.rules),
            "created_at": active.created_at,
        }

    def get_bundle_by_id(self, bundle_id: int) -> dict[str, Any] | None:
        bundle = self.policy_repo.get_bundle(bundle_id)
        if bundle is None:
            return None
        return {
            "bundle_id": bundle.id,
            "bundle": BundleInfo.model_validate(bundle.metadata.__dict__),
            "release_id": bundle.release_id,
            "created_by": bundle.created_by,
            "creation_reason": bundle.creation_reason,
            "promoted_by": bundle.promoted_by,
            "promotion_reason": bundle.promotion_reason,
            "source_bundle_id": bundle.source_bundle_id,
            "integrity_digest": bundle.integrity_digest,
            "compatibility_notes": bundle.compatibility_notes,
            "release_notes": bundle.release_notes,
            "migration_notes": bundle.migration_notes,
            "validation_artifact": bundle.validation_artifact,
            "rules_total": len(bundle.rules),
            "created_at": bundle.created_at,
        }

    def get_bundle_by_version(self, bundle_name: str, version: str) -> dict[str, Any] | None:
        bundle = self.policy_repo.get_bundle_by_version(bundle_name, version)
        if bundle is None:
            return None
        return {
            "bundle_id": bundle.id,
            "bundle": BundleInfo.model_validate(bundle.metadata.__dict__),
            "release_id": bundle.release_id,
            "created_at": bundle.created_at,
        }

    def history(self, bundle_name: str) -> dict[str, Any]:
        return {"bundle_name": bundle_name, "history": self.policy_repo.get_history(bundle_name)}

    def diff(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.policy_repo and payload.get("current_bundle_id") and payload.get("target_bundle_id"):
            current_bundle = self.policy_repo.get_bundle(int(payload["current_bundle_id"]))
            target_bundle = self.policy_repo.get_bundle(int(payload["target_bundle_id"]))
            if current_bundle is None or target_bundle is None:
                raise ValueError("bundle_not_found")
            return diff_rule_sets(current_bundle.rules, target_bundle.rules).__dict__

        current_rules, _ = load_policy_bundle(payload["current_policy_dir"])
        target_rules, _ = load_policy_bundle(payload["target_policy_dir"])
        return diff_rule_sets(current_rules, target_rules).__dict__

    def validate_promotion(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.policy_repo and payload.get("bundle_id"):
            bundle = self.policy_repo.get_bundle(int(payload["bundle_id"]))
            if bundle is None:
                raise ValueError("bundle_not_found")
            source_rules = bundle.rules
            if payload.get("target_lifecycle") == "active":
                active = self.policy_repo.get_active_bundle(bundle.metadata.bundle_name)
                source_rules = active.rules if active else []
            return validate_promotion(
                bundle.metadata.lifecycle,
                payload["target_lifecycle"],
                source_rules,
                bundle.rules,
                validation_artifact=payload.get("validation_artifact"),
                signature_verified=bundle.signature_verified,
                signature_verification_strict=bundle.signature_verification_strict,
            ).__dict__

        source_rules, source_meta = load_policy_bundle(payload["source_policy_dir"])
        target_rules, target_meta = load_policy_bundle(payload["target_policy_dir"])
        signature_verified = True
        signature_strict = bool(payload.get("signature_strict", False))
        if signature_strict:
            manifest_name = payload.get("manifest_filename", self.settings.bundle_release_manifest_filename)
            verified, errors, _ = self.verify_signature(
                policy_dir=payload["target_policy_dir"],
                manifest_filename=manifest_name,
                keyring_dir=payload.get("keyring_dir") or self.settings.bundle_signature_keyring_dir,
                strict=True,
            )
            signature_verified = verified
            if errors and not verified:
                logger.warning("bundle promotion validation signature errors: %s", errors)
        return validate_promotion(
            payload.get("source_lifecycle", source_meta.lifecycle),
            payload.get("target_lifecycle", target_meta.lifecycle),
            source_rules,
            target_rules,
            validation_artifact=payload.get("validation_artifact"),
            signature_verified=signature_verified,
            signature_verification_strict=signature_strict,
        ).__dict__
