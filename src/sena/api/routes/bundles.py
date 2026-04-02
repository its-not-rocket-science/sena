from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter

from sena.api.errors import raise_api_error
from sena.api.runtime import EngineState, verify_bundle_signature
from sena.api.schemas import (
    BundlePromoteRequest,
    BundleRegisterRequest,
    BundleRollbackRequest,
)
from sena.services.bundle_service import BundleService


def create_bundles_router(state: EngineState) -> APIRouter:
    router = APIRouter()
    service = BundleService(
        policy_repo=state.policy_repo,
        settings=state.settings,
        state=state,
        verify_signature=verify_bundle_signature,
    )

    @router.post("/bundle/register")
    def register_bundle(payload: BundleRegisterRequest) -> dict[str, Any]:
        if state.policy_repo is None:
            raise_api_error("policy_store_unavailable")
        try:
            return service.register_bundle(payload)
        except PermissionError as exc:
            errors = (
                str(exc).split(":", 1)[1].split("; ") if ":" in str(exc) else [str(exc)]
            )
            raise_api_error(
                "bundle_signature_verification_failed", details={"errors": errors}
            )
        except ValueError as exc:
            raise_api_error("http_bad_request", details={"reason": str(exc)})

    @router.post("/bundle/promote")
    def promote_bundle(payload: BundlePromoteRequest) -> dict[str, Any]:
        if state.policy_repo is None:
            raise_api_error("policy_store_unavailable")
        try:
            return service.promote_bundle(payload)
        except ValueError as exc:
            if str(exc) == "bundle_not_found":
                raise_api_error(
                    "bundle_not_found", details={"bundle_id": payload.bundle_id}
                )
            raise_api_error(
                "promotion_validation_failed", details={"errors": [str(exc)]}
            )
        except RuntimeError as exc:
            if str(exc).startswith("promotion_validation_failed:"):
                raw = str(exc).split(":", 1)[1]
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    payload = {"messages": raw.split("; "), "failures": []}
                raise_api_error(
                    "promotion_validation_failed",
                    details={
                        "errors": payload.get("messages", []),
                        "failures": payload.get("failures", []),
                    },
                )
            raise_api_error(
                "promotion_validation_failed", details={"errors": [str(exc)]}
            )

    @router.post("/bundle/rollback")
    def rollback_bundle(payload: BundleRollbackRequest) -> dict[str, Any]:
        if state.policy_repo is None:
            raise_api_error("policy_store_unavailable")
        try:
            return service.rollback_bundle(payload)
        except ValueError as exc:
            raise_api_error(
                "promotion_validation_failed", details={"errors": [str(exc)]}
            )

    @router.get("/bundles/active")
    def get_active_bundle(bundle_name: str | None = None) -> dict[str, Any]:
        if state.policy_repo is None:
            raise_api_error("policy_store_unavailable")
        active = service.get_active_bundle(bundle_name)
        if active is None:
            raise_api_error(
                "active_bundle_not_found",
                details={"bundle_name": bundle_name or state.settings.bundle_name},
            )
        return active

    @router.get("/bundles/{bundle_id}")
    def get_bundle_by_id(bundle_id: int) -> dict[str, Any]:
        if state.policy_repo is None:
            raise_api_error("policy_store_unavailable")
        bundle = service.get_bundle_by_id(bundle_id)
        if bundle is None:
            raise_api_error("bundle_not_found", details={"bundle_id": bundle_id})
        return bundle

    @router.get("/bundles/by-version")
    def get_bundle_by_version(bundle_name: str, version: str) -> dict[str, Any]:
        if state.policy_repo is None:
            raise_api_error("policy_store_unavailable")
        bundle = service.get_bundle_by_version(bundle_name, version)
        if bundle is None:
            raise_api_error(
                "bundle_not_found",
                details={"bundle_name": bundle_name, "version": version},
            )
        return bundle

    @router.get("/bundles/history")
    def bundle_history(bundle_name: str) -> dict[str, Any]:
        if state.policy_repo is None:
            raise_api_error("policy_store_unavailable")
        return service.history(bundle_name)

    @router.post("/bundle/diff")
    def bundle_diff(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return service.diff(payload)
        except ValueError:
            raise_api_error("bundle_not_found")

    @router.post("/bundle/promotion/validate")
    def bundle_promotion_validate(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return service.validate_promotion(payload)
        except ValueError:
            raise_api_error("bundle_not_found")

    return router
