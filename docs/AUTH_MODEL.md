# SENA Authentication and Authorization Model

This document defines the runtime security model used by the API layer and clarifies how it differs from policy-evaluation actor fields.

## 1) Separation of concerns

SENA now has four explicit layers:

1. **Authentication** (`sena.api.auth.*provider*`)
   - Validates request credentials (`X-API-Key` or `Authorization: Bearer ...`).
   - Produces an `AuthenticatedIdentity` with provider + claims.
2. **Principal resolution** (`sena.api.auth.PrincipalResolver`)
   - Maps authenticated identity claims to a SENA application principal (`subject`, `role`).
   - Handles JWT role-claim extraction and external-role to internal-role mapping.
3. **Authorization**
   - Endpoint-level RBAC and ABAC checks remain centralized in middleware/runtime.
   - Structured sensitive-operation checks are explicit (`bundle_promotion`, `bundle_rollback`, `audit_config_change`, `exception_approval`).
4. **Policy-time actor identity checks** (`evaluate_policy_actor_identity`)
   - Optional control to ensure evaluation payload `actor_id` matches authenticated JWT `sub` for evaluation routes.
   - Controlled by `SENA_ENFORCE_POLICY_ACTOR_IDENTITY`.

## 2) Auth providers and migration path

SENA supports a provider abstraction (`AuthManager`) that can load one or both providers:

- **API key provider** (current path):
  - `SENA_API_KEY_ENABLED=true`
  - `SENA_API_KEYS=key1:role,key2:role`
- **JWT bearer provider** (OIDC-ready path):
  - `SENA_JWT_AUTH_ENABLED=true`
  - Local/dev verifier currently supports **HS256** signature verification.
  - Verification is intentionally narrow today (shared-secret HS256 only). It is not a complete enterprise OIDC/JWKS validation plane.
  - Future IdP-backed validation can replace provider internals without changing route authorization wiring.

If both providers are enabled, exactly one credential type may be presented per request.

## 3) JWT/OIDC-ready configuration

- `SENA_JWT_AUTH_ENABLED`: enable bearer-token auth.
- `SENA_JWT_HS256_SECRET`: local/dev shared secret for HS256 verification.
- `SENA_JWT_ISSUER`: optional exact `iss` match.
- `SENA_JWT_AUDIENCE`: optional exact `aud` match (or contained in `aud` list).
- `SENA_JWT_REQUIRED_CLAIMS`: comma-separated required claims (default `sub`).
- `SENA_JWT_ROLE_CLAIM`: claim carrying external role(s) (default `roles`).
- `SENA_JWT_ROLE_MAPPING`: external-to-internal mappings (`idp_role:reviewer,...`).
- `SENA_REQUIRE_SIGNED_STEP_UP`: when `true`, sensitive operations require signed step-up assertions (not header presence only).
- `SENA_STEP_UP_HS256_SECRET`: shared secret used to verify signed step-up assertions.
- `SENA_STEP_UP_MAX_AGE_SECONDS`: max assertion age in seconds (default `300`).

Internal supported roles are unchanged:
`admin`, `policy_author`, `reviewer`, `deployer`, `auditor`, `verifier`.

## 4) Sensitive operation checks

The following operations now use explicit structured checks:

- `bundle_promotion`
- `bundle_rollback`
- `audit_config_change`
- `exception_approval`
- `audit_legal_hold`
- `payload_legal_hold`
- `integration_dead_letter_replay`
- `integration_dead_letter_manual_redrive`

These checks enforce separation-of-duties and step-up controls. With `SENA_REQUIRE_SIGNED_STEP_UP=true`, signed assertions are bound to caller identity + operation and include explicit expiry.

### Signed step-up assertion contract (when enabled)

- Header: `X-Step-Up-Auth: v1.<base64url-json-payload>.<base64url-hmac-sha256-signature>`
- Payload fields:
  - `subject`: must match authenticated principal subject.
  - `operation`: must equal the sensitive operation (or `*`).
  - `iat`: issued-at epoch seconds, bounded by `SENA_STEP_UP_MAX_AGE_SECONDS`.
  - `secondary_approver` (required where dual approval applies): must match header-provided secondary approver identity.

## 5) App auth vs policy actor identity

Important distinction:

- **App auth identity**: who is calling the API (`principal.subject`, `principal.role`).
- **Policy identity fields**: data inside evaluation payload (`actor_id`, `actor_role`) used by decision rules.

These are intentionally independent by default to support mediated workflows and service accounts. Enable strict binding with `SENA_ENFORCE_POLICY_ACTOR_IDENTITY=true` when policy actor identity must match JWT subject for evaluation requests.
