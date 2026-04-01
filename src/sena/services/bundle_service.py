from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from sena.api.schemas import BundleInfo, BundlePromoteRequest, BundleRegisterRequest, BundleRollbackRequest
from sena.policy.lifecycle import diff_rule_sets, validate_promotion
from sena.policy.parser import load_policy_bundle

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
        source_rules = stored_bundle.rules
        if payload.target_lifecycle == "active":
            current_active = self.policy_repo.get_active_bundle(stored_bundle.metadata.bundle_name)
            source_rules = current_active.rules if current_active is not None else []

        validation = validate_promotion(
            stored_bundle.metadata.lifecycle,
            payload.target_lifecycle,
            source_rules,
            stored_bundle.rules,
            validation_artifact=payload.validation_artifact,
            signature_verified=stored_bundle.signature_verified,
            signature_verification_strict=stored_bundle.signature_verification_strict,
        )
        if not validation.valid:
            raise RuntimeError("promotion_validation_failed:" + "; ".join(validation.errors))

        self.policy_repo.transition_bundle(
            payload.bundle_id,
            payload.target_lifecycle,
            promoted_by=payload.promoted_by,
            promotion_reason=payload.promotion_reason,
            validation_artifact=payload.validation_artifact,
        )
        active = self.policy_repo.get_active_bundle(self.settings.bundle_name)
        if active is not None:
            self.state.rules = active.rules
            self.state.metadata = active.metadata
        return {"status": "ok", "bundle_id": payload.bundle_id, "lifecycle": payload.target_lifecycle}

    def rollback_bundle(self, payload: BundleRollbackRequest) -> dict[str, Any]:
        self.policy_repo.rollback_bundle(
            payload.bundle_name,
            payload.to_bundle_id,
            promoted_by=payload.promoted_by,
            promotion_reason=payload.promotion_reason,
            validation_artifact=payload.validation_artifact,
        )
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
