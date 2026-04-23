from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from fastapi import Request


VALID_APP_ROLES = {
    "admin",
    "policy_author",
    "reviewer",
    "deployer",
    "auditor",
    "verifier",
}


class AuthError(RuntimeError):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class AuthenticatedIdentity:
    provider: str
    subject: str
    claims: Mapping[str, Any]


@dataclass(frozen=True)
class Principal:
    subject: str
    role: str
    claims: Mapping[str, Any]
    provider: str


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    reason: str | None = None
    required_headers: tuple[str, ...] = ()

    def details(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.reason:
            payload["reason"] = self.reason
        if self.required_headers:
            payload["required_headers"] = list(self.required_headers)
        return payload


SENSITIVE_OPERATION_ACTIONS = {
    "bundle_promotion",
    "bundle_rollback",
    "audit_config_change",
    "exception_approval",
    "audit_legal_hold",
    "payload_legal_hold",
    "integration_dead_letter_replay",
    "integration_dead_letter_manual_redrive",
}

_STEP_UP_REPLAY_CACHE: dict[str, int] = {}


class AuthProvider(Protocol):
    provider_name: str

    def authenticate(self, request: Request) -> AuthenticatedIdentity | None:
        ...


class ApiKeyAuthProvider:
    provider_name = "api_key"

    def __init__(self, key_roles: Mapping[str, str]):
        self._key_roles = key_roles

    def authenticate(self, request: Request) -> AuthenticatedIdentity | None:
        raw_key = request.headers.get("x-api-key")
        if not raw_key:
            return None
        role = self._key_roles.get(raw_key)
        if role is None:
            raise AuthError(
                status_code=401,
                code="unauthorized",
                message="Missing or invalid API key",
            )
        fingerprint = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]
        return AuthenticatedIdentity(
            provider=self.provider_name,
            subject=f"api_key:{fingerprint}",
            claims={"role": role, "credential_type": "api_key"},
        )


class JwtBearerAuthProvider:
    provider_name = "jwt"

    def __init__(
        self,
        *,
        issuer: str | None,
        audience: str | None,
        hs256_secret: str,
        required_claims: tuple[str, ...],
    ):
        self._issuer = issuer
        self._audience = audience
        self._secret = hs256_secret
        self._required_claims = required_claims

    def authenticate(self, request: Request) -> AuthenticatedIdentity | None:
        authz = request.headers.get("authorization", "")
        if not authz:
            return None
        scheme, _, token = authz.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise AuthError(
                status_code=401,
                code="invalid_authentication",
                message="Authorization header must use Bearer token format",
            )
        payload = _validate_hs256_jwt(
            token,
            secret=self._secret,
            issuer=self._issuer,
            audience=self._audience,
            required_claims=self._required_claims,
        )
        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise AuthError(
                status_code=401,
                code="invalid_authentication",
                message="JWT token is missing required 'sub' claim",
            )
        return AuthenticatedIdentity(
            provider=self.provider_name,
            subject=subject,
            claims=payload,
        )


class PrincipalResolver:
    def __init__(
        self,
        *,
        jwt_role_claim: str,
        jwt_role_mapping: Mapping[str, str],
    ):
        self._jwt_role_claim = jwt_role_claim
        self._jwt_role_mapping = dict(jwt_role_mapping)

    def resolve(self, identity: AuthenticatedIdentity) -> Principal:
        if identity.provider == "api_key":
            role = str(identity.claims.get("role", "")).strip()
            return self._build_principal(identity, role)

        role = self._resolve_jwt_role(identity.claims)
        return self._build_principal(identity, role)

    def _build_principal(self, identity: AuthenticatedIdentity, role: str) -> Principal:
        if role not in VALID_APP_ROLES:
            raise AuthError(
                status_code=403,
                code="forbidden",
                message=f"Resolved role '{role}' is not supported",
                details={"reason": "role_mapping_failed", "role": role},
            )
        return Principal(
            subject=identity.subject,
            role=role,
            claims=identity.claims,
            provider=identity.provider,
        )

    def _resolve_jwt_role(self, claims: Mapping[str, Any]) -> str:
        if self._jwt_role_claim not in claims:
            raise AuthError(
                status_code=403,
                code="forbidden",
                message="JWT token has no role claim",
                details={
                    "reason": "role_mapping_failed",
                    "claim": self._jwt_role_claim,
                },
            )
        raw_role = claims[self._jwt_role_claim]
        candidates = raw_role if isinstance(raw_role, list) else [raw_role]
        normalized = [str(item).strip() for item in candidates if str(item).strip()]
        if not normalized:
            raise AuthError(
                status_code=403,
                code="forbidden",
                message="JWT role claim is empty",
                details={"reason": "role_mapping_failed", "claim": self._jwt_role_claim},
            )
        if not self._jwt_role_mapping:
            return normalized[0]
        for item in normalized:
            mapped = self._jwt_role_mapping.get(item)
            if mapped:
                return mapped
        raise AuthError(
            status_code=403,
            code="forbidden",
            message="No JWT role value maps to a supported application role",
            details={"reason": "role_mapping_failed", "values": normalized},
        )


class AuthManager:
    def __init__(
        self,
        *,
        providers: tuple[AuthProvider, ...],
        resolver: PrincipalResolver,
        auth_required: bool,
    ):
        self._providers = providers
        self._resolver = resolver
        self._auth_required = auth_required

    def authenticate_request(self, request: Request) -> Principal | None:
        identities: list[AuthenticatedIdentity] = []
        for provider in self._providers:
            identity = provider.authenticate(request)
            if identity is not None:
                identities.append(identity)
        if len(identities) > 1:
            raise AuthError(
                status_code=400,
                code="http_bad_request",
                message="Provide exactly one authentication mechanism per request",
                details={"reason": "multiple_auth_credentials"},
            )
        if not identities:
            if self._auth_required:
                raise AuthError(
                    status_code=401,
                    code="unauthorized",
                    message="Authentication required",
                )
            return None
        return self._resolver.resolve(identities[0])


def build_auth_manager(
    *,
    settings: Any,
    api_key_roles: Mapping[str, str],
) -> AuthManager:
    providers: list[AuthProvider] = []
    if settings.enable_api_key_auth:
        providers.append(ApiKeyAuthProvider(api_key_roles))
    if settings.enable_jwt_auth:
        providers.append(
            JwtBearerAuthProvider(
                issuer=settings.jwt_issuer,
                audience=settings.jwt_audience,
                hs256_secret=str(settings.jwt_hs256_secret),
                required_claims=tuple(settings.jwt_required_claims),
            )
        )
    resolver = PrincipalResolver(
        jwt_role_claim=settings.jwt_role_claim,
        jwt_role_mapping=dict(settings.jwt_role_mapping),
    )
    return AuthManager(
        providers=tuple(providers),
        resolver=resolver,
        auth_required=bool(providers),
    )


def evaluate_policy_actor_identity(
    *,
    principal: Principal | None,
    request_path: str,
    body_payload: Mapping[str, Any],
    enforce: bool,
) -> PermissionDecision:
    if not enforce or principal is None:
        return PermissionDecision(allowed=True)
    if request_path not in {"/v1/evaluate", "/v1/evaluate/batch", "/v1/evaluate/review-package"}:
        return PermissionDecision(allowed=True)
    actor_id = body_payload.get("actor_id")
    if not isinstance(actor_id, str) or not actor_id.strip():
        return PermissionDecision(allowed=True)
    if principal.provider != "jwt":
        return PermissionDecision(allowed=True)
    if actor_id != principal.subject:
        return PermissionDecision(
            allowed=False,
            reason="actor_identity_mismatch",
        )
    return PermissionDecision(allowed=True)


def evaluate_sensitive_operation(
    *,
    operation: str,
    principal: Principal | None,
    headers: Mapping[str, str],
    require_signed_step_up: bool = False,
    step_up_hs256_secret: str | None = None,
    step_up_max_age_seconds: int = 300,
    step_up_issuer: str | None = None,
    step_up_key_id: str | None = None,
) -> PermissionDecision:
    if principal is None:
        return PermissionDecision(allowed=True)
    if principal.role == "admin":
        return PermissionDecision(allowed=True)

    if operation == "bundle_promotion":
        if principal.role in {"policy_author", "reviewer"}:
            return PermissionDecision(
                allowed=False,
                reason="separation_of_duties: role cannot deploy bundles",
            )
        step_up_decision, step_up_assertion = _evaluate_step_up_assertion(
            operation=operation,
            principal=principal,
            headers=headers,
            require_signed_step_up=require_signed_step_up,
            step_up_hs256_secret=step_up_hs256_secret,
            step_up_max_age_seconds=step_up_max_age_seconds,
            step_up_issuer=step_up_issuer,
            step_up_key_id=step_up_key_id,
        )
        if not step_up_decision.allowed:
            return step_up_decision
        if require_signed_step_up and step_up_assertion is None:
            return PermissionDecision(allowed=False, reason="step_up_assertion_invalid")
        primary_approver = (
            str(step_up_assertion.get("sub", "")).strip()
            if step_up_assertion
            else str(headers.get("x-approver-id", "")).strip()
        )
        secondary_approver = (
            str(step_up_assertion.get("secondary_sub", "")).strip()
            if step_up_assertion
            else str(headers.get("x-secondary-approver-id", "")).strip()
        )
        if not primary_approver or not secondary_approver:
            return PermissionDecision(
                allowed=False,
                reason="dual_approval_required",
                required_headers=("x-approver-id", "x-secondary-approver-id"),
            )
        if primary_approver != principal.subject:
            return PermissionDecision(
                allowed=False,
                reason="approver_identity_mismatch",
            )
        if len({primary_approver, secondary_approver}) != 2:
            return PermissionDecision(
                allowed=False,
                reason="dual_approval_requires_distinct_approvers",
            )

    if operation == "bundle_rollback":
        step_up_decision, _ = _evaluate_step_up_assertion(
            operation=operation,
            principal=principal,
            headers=headers,
            require_signed_step_up=require_signed_step_up,
            step_up_hs256_secret=step_up_hs256_secret,
            step_up_max_age_seconds=step_up_max_age_seconds,
            step_up_issuer=step_up_issuer,
            step_up_key_id=step_up_key_id,
        )
        if not step_up_decision.allowed:
            return step_up_decision

    if operation == "audit_config_change":
        if principal.role not in {"reviewer", "auditor"}:
            return PermissionDecision(
                allowed=False,
                reason="separation_of_duties: only reviewer or auditor may change audit configuration",
            )
        step_up_decision, step_up_assertion = _evaluate_step_up_assertion(
            operation=operation,
            principal=principal,
            headers=headers,
            require_signed_step_up=require_signed_step_up,
            step_up_hs256_secret=step_up_hs256_secret,
            step_up_max_age_seconds=step_up_max_age_seconds,
            step_up_issuer=step_up_issuer,
            step_up_key_id=step_up_key_id,
        )
        if not step_up_decision.allowed:
            return step_up_decision
        secondary_approver = (
            str(step_up_assertion.get("secondary_sub", "")).strip()
            if step_up_assertion
            else str(headers.get("x-secondary-approver-id", "")).strip()
        )
        if not secondary_approver:
            return PermissionDecision(
                allowed=False,
                reason="secondary_approval_required",
                required_headers=("x-secondary-approver-id",),
            )
        if secondary_approver == principal.subject:
            return PermissionDecision(
                allowed=False,
                reason="dual_approval_requires_distinct_approvers",
            )

    if operation == "exception_approval":
        if principal.role not in {"reviewer", "auditor"}:
            return PermissionDecision(
                allowed=False,
                reason="separation_of_duties: only reviewer or auditor may approve exceptions",
            )
        step_up_decision, _ = _evaluate_step_up_assertion(
            operation=operation,
            principal=principal,
            headers=headers,
            require_signed_step_up=require_signed_step_up,
            step_up_hs256_secret=step_up_hs256_secret,
            step_up_max_age_seconds=step_up_max_age_seconds,
            step_up_issuer=step_up_issuer,
            step_up_key_id=step_up_key_id,
        )
        if not step_up_decision.allowed:
            return step_up_decision

    if operation == "audit_legal_hold":
        if principal.role != "auditor":
            return PermissionDecision(
                allowed=False,
                reason="separation_of_duties: only auditor may apply legal hold",
            )
        step_up_decision, _ = _evaluate_step_up_assertion(
            operation=operation,
            principal=principal,
            headers=headers,
            require_signed_step_up=require_signed_step_up,
            step_up_hs256_secret=step_up_hs256_secret,
            step_up_max_age_seconds=step_up_max_age_seconds,
            step_up_issuer=step_up_issuer,
            step_up_key_id=step_up_key_id,
        )
        if not step_up_decision.allowed:
            return step_up_decision

    if operation == "payload_legal_hold":
        if principal.role != "auditor":
            return PermissionDecision(
                allowed=False,
                reason="separation_of_duties: only auditor may apply payload legal hold",
            )
        step_up_decision, _ = _evaluate_step_up_assertion(
            operation=operation,
            principal=principal,
            headers=headers,
            require_signed_step_up=require_signed_step_up,
            step_up_hs256_secret=step_up_hs256_secret,
            step_up_max_age_seconds=step_up_max_age_seconds,
            step_up_issuer=step_up_issuer,
            step_up_key_id=step_up_key_id,
        )
        if not step_up_decision.allowed:
            return step_up_decision

    if operation in {"integration_dead_letter_replay", "integration_dead_letter_manual_redrive"}:
        if principal.role != "auditor":
            return PermissionDecision(
                allowed=False,
                reason="separation_of_duties: only auditor may mutate integration dead-letter state",
            )
        step_up_decision, _ = _evaluate_step_up_assertion(
            operation=operation,
            principal=principal,
            headers=headers,
            require_signed_step_up=require_signed_step_up,
            step_up_hs256_secret=step_up_hs256_secret,
            step_up_max_age_seconds=step_up_max_age_seconds,
            step_up_issuer=step_up_issuer,
            step_up_key_id=step_up_key_id,
        )
        if not step_up_decision.allowed:
            return step_up_decision

    return PermissionDecision(allowed=True)


def _evaluate_step_up_assertion(
    *,
    operation: str,
    principal: Principal,
    headers: Mapping[str, str],
    require_signed_step_up: bool,
    step_up_hs256_secret: str | None,
    step_up_max_age_seconds: int,
    step_up_issuer: str | None,
    step_up_key_id: str | None,
) -> tuple[PermissionDecision, dict[str, Any] | None]:
    step_up = str(headers.get("x-step-up-auth", "")).strip()
    if not step_up:
        return PermissionDecision(
            allowed=False,
            reason="step_up_auth_required",
            required_headers=("x-step-up-auth",),
        ), None
    if not require_signed_step_up:
        return PermissionDecision(allowed=True), None
    if not step_up_hs256_secret:
        return PermissionDecision(
            allowed=False,
            reason="step_up_verification_not_configured",
        ), None
    try:
        assertion = _parse_step_up_assertion(
            step_up,
            secret=step_up_hs256_secret,
            max_age_seconds=step_up_max_age_seconds,
            expected_issuer=step_up_issuer,
            expected_key_id=step_up_key_id,
        )
    except AuthError as exc:
        return PermissionDecision(
            allowed=False,
            reason=str(exc.details.get("reason", "step_up_assertion_invalid")),
        ), None
    if assertion.get("sub") != principal.subject:
        return PermissionDecision(
            allowed=False,
            reason="step_up_subject_mismatch",
        ), None
    assertion_operation = assertion.get("op")
    if assertion_operation not in {"*", operation}:
        return PermissionDecision(
            allowed=False,
            reason="step_up_operation_mismatch",
        ), None
    replay_key = f"{assertion.get('iss')}:{assertion.get('kid')}:{assertion.get('jti')}"
    if _is_replayed_step_up_assertion(replay_key=replay_key, expires_at=int(assertion["exp"])):
        return PermissionDecision(
            allowed=False,
            reason="step_up_replay_detected",
        ), None
    return PermissionDecision(allowed=True), assertion


def _parse_step_up_assertion(
    token: str,
    *,
    secret: str,
    max_age_seconds: int,
    expected_issuer: str | None,
    expected_key_id: str | None,
) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != "v1":
        raise AuthError(
            status_code=401,
            code="invalid_authentication",
            message="Malformed step-up assertion token",
            details={"reason": "step_up_assertion_invalid"},
        )
    _, payload_segment, signature_segment = parts
    signing_input = f"v1.{payload_segment}".encode("utf-8")
    expected_sig = base64.urlsafe_b64encode(
        hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    ).rstrip(b"=").decode("utf-8")
    if not hmac.compare_digest(expected_sig, signature_segment):
        raise AuthError(
            status_code=401,
            code="invalid_authentication",
            message="Step-up assertion signature verification failed",
            details={"reason": "step_up_assertion_invalid"},
        )
    try:
        payload = json.loads(_decode_segment(payload_segment).decode("utf-8"))
    except Exception as exc:
        raise AuthError(
            status_code=401,
            code="invalid_authentication",
            message="Step-up assertion payload must be valid JSON",
            details={"reason": "step_up_assertion_invalid"},
        ) from exc
    if not isinstance(payload, dict):
        raise AuthError(
            status_code=401,
            code="invalid_authentication",
            message="Step-up assertion payload must be an object",
            details={"reason": "step_up_assertion_invalid"},
        )
    issuer = str(payload.get("iss", "")).strip()
    if not issuer:
        raise AuthError(
            status_code=401,
            code="invalid_authentication",
            message="Step-up assertion missing issuer",
            details={"reason": "step_up_assertion_invalid"},
        )
    if expected_issuer and issuer != expected_issuer:
        raise AuthError(
            status_code=401,
            code="invalid_authentication",
            message="Step-up assertion issuer mismatch",
            details={"reason": "step_up_issuer_mismatch"},
        )
    key_id = str(payload.get("kid", "")).strip()
    if not key_id:
        raise AuthError(
            status_code=401,
            code="invalid_authentication",
            message="Step-up assertion missing key id",
            details={"reason": "step_up_assertion_invalid"},
        )
    if expected_key_id and key_id != expected_key_id:
        raise AuthError(
            status_code=401,
            code="invalid_authentication",
            message="Step-up assertion key id mismatch",
            details={"reason": "step_up_key_mismatch"},
        )
    for claim in ("sub", "op", "jti", "exp", "iat"):
        if claim not in payload:
            raise AuthError(
                status_code=401,
                code="invalid_authentication",
                message=f"Step-up assertion missing {claim}",
                details={"reason": "step_up_assertion_invalid"},
            )
    now = int(time.time())
    issued = int(payload["iat"])
    if issued > now + 30:
        raise AuthError(
            status_code=401,
            code="invalid_authentication",
            message="Step-up assertion iat is in the future",
            details={"reason": "step_up_assertion_invalid"},
        )
    if now - issued > max_age_seconds:
        raise AuthError(
            status_code=401,
            code="invalid_authentication",
            message="Step-up assertion is expired",
            details={"reason": "step_up_assertion_expired"},
        )
    expires_at = int(payload["exp"])
    if expires_at <= issued or expires_at < now:
        raise AuthError(
            status_code=401,
            code="invalid_authentication",
            message="Step-up assertion is expired",
            details={"reason": "step_up_assertion_expired"},
        )
    return payload


def parse_step_up_assertion_payload(
    *,
    token: str,
    secret: str,
    max_age_seconds: int,
    expected_issuer: str | None,
    expected_key_id: str | None,
) -> dict[str, Any]:
    return _parse_step_up_assertion(
        token,
        secret=secret,
        max_age_seconds=max_age_seconds,
        expected_issuer=expected_issuer,
        expected_key_id=expected_key_id,
    )


def _is_replayed_step_up_assertion(*, replay_key: str, expires_at: int) -> bool:
    now = int(time.time())
    expired_keys = [key for key, expiry in _STEP_UP_REPLAY_CACHE.items() if expiry < now]
    for key in expired_keys:
        _STEP_UP_REPLAY_CACHE.pop(key, None)
    if replay_key in _STEP_UP_REPLAY_CACHE:
        return True
    _STEP_UP_REPLAY_CACHE[replay_key] = expires_at
    return False


def _decode_segment(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _validate_hs256_jwt(
    token: str,
    *,
    secret: str,
    issuer: str | None,
    audience: str | None,
    required_claims: tuple[str, ...],
) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthError(
            status_code=401,
            code="invalid_authentication",
            message="Malformed JWT token",
        )
    header_raw, payload_raw, signature = parts
    try:
        header = json.loads(_decode_segment(header_raw).decode("utf-8"))
        payload = json.loads(_decode_segment(payload_raw).decode("utf-8"))
    except Exception as exc:
        raise AuthError(
            status_code=401,
            code="invalid_authentication",
            message="JWT token is not valid JSON",
        ) from exc

    if header.get("alg") != "HS256":
        raise AuthError(
            status_code=401,
            code="invalid_authentication",
            message="Only HS256 JWT tokens are supported in this deployment",
        )

    signing_input = f"{header_raw}.{payload_raw}".encode("utf-8")
    expected_sig = base64.urlsafe_b64encode(
        hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    ).rstrip(b"=").decode("utf-8")
    if not hmac.compare_digest(expected_sig, signature):
        raise AuthError(
            status_code=401,
            code="invalid_authentication",
            message="JWT token signature verification failed",
        )

    now = int(time.time())
    exp = payload.get("exp")
    if exp is not None and int(exp) < now:
        raise AuthError(
            status_code=401,
            code="invalid_authentication",
            message="JWT token is expired",
        )
    nbf = payload.get("nbf")
    if nbf is not None and int(nbf) > now:
        raise AuthError(
            status_code=401,
            code="invalid_authentication",
            message="JWT token is not yet valid",
        )
    if issuer is not None and payload.get("iss") != issuer:
        raise AuthError(
            status_code=401,
            code="invalid_authentication",
            message="JWT token issuer does not match configuration",
        )
    if audience is not None:
        token_aud = payload.get("aud")
        if isinstance(token_aud, list):
            matches = audience in token_aud
        else:
            matches = token_aud == audience
        if not matches:
            raise AuthError(
                status_code=401,
                code="invalid_authentication",
                message="JWT token audience does not match configuration",
            )
    for claim in required_claims:
        if claim not in payload:
            raise AuthError(
                status_code=401,
                code="invalid_authentication",
                message=f"JWT token missing required claim '{claim}'",
            )
    return payload
