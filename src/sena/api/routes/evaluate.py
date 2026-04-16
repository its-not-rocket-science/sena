from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from sena.api.dependencies import (
    idempotency_key_lock,
    idempotency_request_fingerprint,
    persist_idempotency_response,
)
from sena.api.errors import raise_api_error
from sena.api.runtime import EngineState, parse_default_decision
from sena.api.schemas import (
    BatchEvaluateRequest,
    DecisionAttestationSignRequest,
    DecisionAttestationsResponse,
    EvaluateRequest,
    JobAcceptedResponse,
    JobResultResponse,
    JobStatusResponse,
    ReplayDriftRequest,
    SimulationJobSubmitRequest,
    SimulationReplayRequest,
    SimulationRequest,
)
from sena.services.async_jobs import TERMINAL_JOB_STATUSES, JobRecord
from sena.services.audit_service import AuditService
from sena.services.evaluation_service import EvaluationService
from sena.services.reliability_service import QueueOverflowError
from sena.verification import (
    DecisionAttestation,
    VERIFIER_ROLE,
    sign_attestation,
    verify_attestation_signature,
)

ERROR_RESPONSES = {
    400: {"description": "Invalid request or evaluation failure."},
    401: {"description": "Missing or invalid API key."},
    403: {"description": "API key is not authorized."},
    429: {"description": "Rate limit exceeded."},
    500: {"description": "Unexpected server error."},
}


def create_evaluate_router(state: EngineState) -> APIRouter:
    router = APIRouter(tags=["evaluation"], responses=ERROR_RESPONSES)
    evaluation_service = EvaluationService(
        state=state, audit_service=AuditService(state.settings.audit_sink_jsonl)
    )

    def _evaluate(req: EvaluateRequest, request: Request) -> dict:
        try:
            return state.processing_service.enqueue_and_process(
                {
                    "event_type": "evaluate",
                    "payload": req.model_dump(),
                    "request_id": request.state.request_id,
                }
            )
        except QueueOverflowError as exc:
            raise_api_error("rate_limited", details={"reason": str(exc)})
        except Exception as exc:  # pragma: no cover
            state.processing_store.enqueue_dead_letter(
                {
                    "event_type": "evaluate",
                    "payload": req.model_dump(),
                    "request_id": request.state.request_id,
                },
                str(exc),
            )
            raise_api_error("evaluation_error", details={"reason": str(exc)})

    def _ok(payload: dict) -> dict:
        if "status" not in payload:
            payload["status"] = "ok"
        return payload

    def _serialize_job(record: JobRecord) -> dict:
        return JobStatusResponse(**record.to_status_payload()).model_dump()

    def _simulation_payload(req: SimulationRequest) -> dict:
        return evaluation_service.simulate_policy_change(
            baseline_policy_dir=req.baseline_policy_dir,
            candidate_policy_dir=req.candidate_policy_dir,
            scenarios=[item.model_dump() for item in req.scenarios],
        )

    def _submit_simulation_job(req: SimulationJobSubmitRequest) -> dict:
        record = state.job_manager.submit(
            runner=lambda: _ok(_simulation_payload(req)),
            job_type="simulation",
            timeout_seconds=req.timeout_seconds,
        )
        return JobAcceptedResponse(
            status="accepted", job=JobStatusResponse(**record.to_status_payload())
        ).model_dump()

    @router.post(
        "/evaluate",
        summary="Evaluate one action proposal",
        description="Returns the policy decision trace for one action proposal.",
    )
    def evaluate(
        req: EvaluateRequest,
        request: Request,
    ) -> dict | Response:
        key = request.headers.get("Idempotency-Key")
        request_payload = req.model_dump()
        with idempotency_key_lock(key):
            if key:
                existing = state.processing_store.get_idempotency_entry(key)
                if existing is not None:
                    cached_response, fingerprint = existing
                    incoming_fingerprint = idempotency_request_fingerprint(
                        request, request_payload
                    )
                    if (
                        fingerprint is not None
                        and incoming_fingerprint is not None
                        and fingerprint != incoming_fingerprint
                    ):
                        raise_api_error(
                            "validation_error",
                            message="Idempotency-Key has already been used with a different payload.",
                            details={"reason": "idempotency_key_conflict"},
                            status_code=409,
                        )
                    return Response(
                        content=cached_response,
                        media_type="application/json",
                        status_code=200,
                    )
            result = _evaluate(req, request)
            result = _ok(result)
            determinism_contract = result.get("determinism_contract")
            if (
                isinstance(determinism_contract, dict)
                and "canonical_artifacts" not in result
            ):
                result["canonical_artifacts"] = {
                    "canonical_replay_payload": determinism_contract.get(
                        "canonical_replay_payload", {}
                    ),
                    "operational_metadata": determinism_contract.get(
                        "operational_metadata", {}
                    ),
                }
            if req.dry_run:
                result["dry_run"] = True
            persist_idempotency_response(
                request, result, request_payload=request_payload
            )
            return result

    @router.post(
        "/evaluate/review-package",
        summary="Evaluate and generate review package",
        description="Runs evaluation and returns a deterministic decision-review package.",
    )
    def evaluate_review_package(req: EvaluateRequest, request: Request) -> dict:
        try:
            proposal = evaluation_service.build_action_proposal(
                action_type=req.action_type,
                request_id=req.request_id or request.state.request_id,
                actor_id=req.actor_id,
                actor_role=req.actor_role,
                attributes=req.attributes,
                action_origin=req.action_origin,
                ai_metadata=req.ai_metadata.model_dump() if req.ai_metadata else None,
                autonomous_metadata=req.autonomous_metadata.model_dump()
                if req.autonomous_metadata
                else None,
            )
            result = evaluation_service.evaluate_review_package(
                proposal=proposal,
                facts=req.facts,
                endpoint="/v1/evaluate/review-package",
                default_decision=parse_default_decision(req.default_decision),
                strict_require_allow=req.strict_require_allow,
            )
            return _ok(result)
        except Exception as exc:  # pragma: no cover
            raise_api_error("evaluation_error", details={"reason": str(exc)})

    @router.post(
        "/evaluate/batch",
        summary="Evaluate a batch",
        description="Evaluates up to 500 requests and returns ordered results.",
    )
    def evaluate_batch(req: BatchEvaluateRequest, request: Request) -> dict:
        return _ok(
            {
                "count": len(req.items),
                "results": [_evaluate(item, request) for item in req.items],
            }
        )

    @router.post("/simulation", summary="Simulate bundle impact")
    def simulation(
        req: SimulationRequest,
        execution_mode: str = Query(default="auto", pattern="^(sync|async|auto)$"),
    ) -> dict:
        sync_fast_path_limit = 25
        if execution_mode == "sync":
            return _ok(_simulation_payload(req))
        if execution_mode == "auto" and len(req.scenarios) <= sync_fast_path_limit:
            return _ok(_simulation_payload(req))
        submit_req = SimulationJobSubmitRequest(**req.model_dump())
        return _submit_simulation_job(submit_req)

    @router.post(
        "/jobs/simulation",
        response_model=JobAcceptedResponse,
        summary="Submit simulation as asynchronous job",
    )
    def submit_simulation_job(req: SimulationJobSubmitRequest) -> dict:
        return _submit_simulation_job(req)

    @router.get(
        "/jobs/{job_id}",
        response_model=JobStatusResponse,
        summary="Get asynchronous job status",
    )
    def get_job_status(job_id: str) -> dict:
        record = state.job_manager.get(job_id)
        if record is None:
            raise_api_error("http_not_found", message=f"Job not found for '{job_id}'.")
        return _serialize_job(record)

    @router.get(
        "/jobs/{job_id}/result",
        response_model=JobResultResponse,
        summary="Fetch asynchronous job result payload",
    )
    def get_job_result(job_id: str) -> dict:
        record = state.job_manager.get(job_id)
        if record is None:
            raise_api_error("http_not_found", message=f"Job not found for '{job_id}'.")
        if record.status == "succeeded" and isinstance(record.result, dict):
            return JobResultResponse(
                job_id=job_id, status="succeeded", result=record.result
            ).model_dump()
        if record.status in TERMINAL_JOB_STATUSES:
            raise_api_error(
                "http_bad_request",
                message=f"Job '{job_id}' completed with status '{record.status}' and has no result.",
                details={"job": _serialize_job(record)},
            )
        raise_api_error(
            "http_bad_request",
            message=f"Job '{job_id}' is not complete yet.",
            details={"job": _serialize_job(record)},
        )

    @router.post(
        "/jobs/{job_id}/cancel",
        response_model=JobStatusResponse,
        summary="Request asynchronous job cancellation",
    )
    def cancel_job(job_id: str) -> dict:
        record = state.job_manager.cancel(job_id)
        if record is None:
            raise_api_error("http_not_found", message=f"Job not found for '{job_id}'.")
        return _serialize_job(record)

    @router.post("/replay/drift", summary="Replay historical payloads for drift")
    def replay_drift(req: ReplayDriftRequest) -> dict:
        return _ok(
            evaluation_service.replay_policy_drift(
                replay_payload=req.replay_payload,
                baseline_policy_dir=req.baseline_policy_dir,
                candidate_policy_dir=req.candidate_policy_dir,
                baseline_mapping_mode=req.baseline_mapping_mode,
                baseline_mapping_config_path=req.baseline_mapping_config_path,
                candidate_mapping_mode=req.candidate_mapping_mode,
                candidate_mapping_config_path=req.candidate_mapping_config_path,
            )
        )

    @router.post("/simulation/replay", summary="Replay recent audit traffic")
    def simulation_replay(req: SimulationReplayRequest) -> dict:
        window_seconds = 3600 if req.window == "last_1_hour" else 86400
        try:
            return _ok(
                evaluation_service.replay_recent_traffic(
                    audit_path=state.settings.audit_sink_jsonl,
                    proposed_policy_dir=req.proposed_policy_dir,
                    window_seconds=window_seconds,
                    max_samples=req.max_samples,
                )
            )
        except ValueError as exc:
            raise_api_error("http_bad_request", details={"reason": str(exc)})

    @router.get(
        "/decision/{decision_id}/explanation",
        summary="Export decision explanation",
        description=(
            "Returns a role-specific explanation object. "
            "Use view=analyst for concise output or view=auditor for full trace."
        ),
    )
    def get_decision_explanation(
        decision_id: str,
        view: str = Query(default="auditor", pattern="^(analyst|auditor)$"),
    ) -> dict:
        stored = state.processing_store.get_decision_explanation(decision_id)
        if stored is None:
            raise_api_error(
                "http_not_found",
                message=f"Decision explanation not found for '{decision_id}'.",
            )
        payload = stored.get(view)
        if not isinstance(payload, dict):
            raise_api_error(
                "http_not_found",
                message=(
                    f"Decision explanation view '{view}' not found for '{decision_id}'."
                ),
            )
        return payload

    @router.post(
        "/decision/{decision_id}/attestations/sign",
        summary="Sign a decision attestation",
        description=(
            "Allows third-party verifier role to sign an immutable decision hash. "
            "Returns persisted attestation with verification status."
        ),
    )
    def sign_decision_attestation(
        decision_id: str,
        req: DecisionAttestationSignRequest,
    ) -> dict:
        decision_hash = state.processing_store.get_decision_hash(decision_id)
        if decision_hash is None:
            raise_api_error(
                "http_not_found",
                message=f"Decision not found for '{decision_id}'.",
            )
        if req.signer_role != VERIFIER_ROLE:
            raise_api_error(
                "http_bad_request",
                message="Only verifier role can sign decision attestations.",
            )
        attestation = sign_attestation(
            decision_id=decision_id,
            decision_hash=decision_hash,
            signer_id=req.signer_id,
            signer_role=req.signer_role,
            signing_key=req.signing_key,
            key_id=req.key_id,
        )
        state.processing_store.store_decision_attestation(attestation.to_dict())
        verified = verify_attestation_signature(
            attestation=attestation,
            decision_hash=decision_hash,
            signing_key=req.signing_key,
        )
        return {
            **attestation.to_dict(),
            "verified": verified,
        }

    @router.get(
        "/decision/{decision_id}/attestations",
        response_model=DecisionAttestationsResponse,
        summary="List decision attestations",
        description="Returns all third-party signatures for one decision.",
    )
    def get_decision_attestations(decision_id: str) -> dict:
        decision_hash = state.processing_store.get_decision_hash(decision_id)
        if decision_hash is None:
            raise_api_error(
                "http_not_found",
                message=f"Decision not found for '{decision_id}'.",
            )

        rows = state.processing_store.list_decision_attestations(decision_id)
        attestations: list[dict[str, str | bool]] = []
        for row in rows:
            attestation = DecisionAttestation(
                attestation_id=str(row["attestation_id"]),
                decision_id=str(row["decision_id"]),
                decision_hash=str(row["decision_hash"]),
                signer_id=str(row["signer_id"]),
                signer_role=str(row["signer_role"]),
                key_id=str(row["key_id"]),
                signature=str(row["signature"]),
                signed_at=str(row["signed_at"]),
            )
            attestations.append(
                {
                    **attestation.to_dict(),
                    "verified": attestation.decision_hash == decision_hash,
                }
            )
        return {
            "decision_id": decision_id,
            "attestations": attestations,
        }

    return router
