from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request

from sena.api.auth import evaluate_sensitive_operation
from sena.api.errors import raise_api_error
from sena.api.runtime import EngineState, verify_bundle_signature
from sena.api.schemas import (
    BundlePromoteRequest,
    BundleRegisterRequest,
    BundleRollbackRequest,
)
from sena.services.bundle_service import BundleService


def create_bundles_router(state: EngineState) -> APIRouter:
    router = APIRouter(tags=["bundles"], responses={400:{"description":"Bad request"},401:{"description":"Unauthorized"},403:{"description":"Forbidden"},429:{"description":"Rate limited"},500:{"description":"Server error"}})
    service = BundleService(
        policy_repo=state.policy_repo,
        settings=state.settings,
        state=state,
        verify_signature=verify_bundle_signature,
    )

    @router.post("/bundle/register", summary="Register policy bundle")
    def register_bundle(payload: BundleRegisterRequest, request: Request) -> dict[str, Any]:
        role = getattr(request.state, "api_role", "")
        if role == "deployer":
            raise_api_error(
                "forbidden",
                details={"reason": "separation_of_duties: deployer cannot author bundles"},
            )
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

    @router.post("/bundle/promote", summary="Promote policy bundle lifecycle")
    def promote_bundle(payload: BundlePromoteRequest, request: Request) -> dict[str, Any]:
        principal = getattr(request.state, "auth_principal", None)
        decision = evaluate_sensitive_operation(
            operation="bundle_promotion",
            principal=principal,
            headers=request.headers,
        )
        if not decision.allowed:
            raise_api_error("forbidden", details=decision.details())
        if principal:
            primary_approver = request.headers.get("x-approver-id")
            secondary_approver = request.headers.get("x-secondary-approver-id")
            merged_attestations = sorted(
                {
                    *(payload.approver_attestations or []),
                    primary_approver or "",
                    secondary_approver or "",
                }
            )
            payload = payload.model_copy(
                update={"approver_attestations": merged_attestations}
            )
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

    @router.post("/bundle/rollback", summary="Rollback bundle to known version")
    def rollback_bundle(payload: BundleRollbackRequest, request: Request) -> dict[str, Any]:
        principal = getattr(request.state, "auth_principal", None)
        decision = evaluate_sensitive_operation(
            operation="bundle_rollback",
            principal=principal,
            headers=request.headers,
        )
        if not decision.allowed:
            raise_api_error("forbidden", details=decision.details())
        if state.policy_repo is None:
            raise_api_error("policy_store_unavailable")
        try:
            return service.rollback_bundle(payload)
        except ValueError as exc:
            raise_api_error(
                "promotion_validation_failed", details={"errors": [str(exc)]}
            )

    @router.get("/bundles/active", summary="Get active bundle")
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

    @router.get("/bundles/{bundle_id}", summary="Get bundle by id")
    def get_bundle_by_id(bundle_id: int) -> dict[str, Any]:
        if state.policy_repo is None:
            raise_api_error("policy_store_unavailable")
        bundle = service.get_bundle_by_id(bundle_id)
        if bundle is None:
            raise_api_error("bundle_not_found", details={"bundle_id": bundle_id})
        return bundle

    @router.get("/bundles/by-version", summary="Get bundle by name and version")
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

    @router.get("/bundles/history", summary="Get lifecycle history")
    def bundle_history(bundle_name: str) -> dict[str, Any]:
        if state.policy_repo is None:
            raise_api_error("policy_store_unavailable")
        return service.history(bundle_name)

    @router.post("/bundle/diff", summary="Diff two bundle revisions")
    def bundle_diff(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return service.diff(payload)
        except ValueError:
            raise_api_error("bundle_not_found")

    @router.post("/bundle/promotion/validate", summary="Validate promotion gates")
    def bundle_promotion_validate(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return service.validate_promotion(payload)
        except ValueError:
            raise_api_error("bundle_not_found")

    return router
