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
- `SENA_REQUIRE_SIGNED_STEP_UP`: defaults to `true`. Sensitive operations require signed step-up assertions.
- `SENA_STEP_UP_HS256_SECRET`: shared secret used to verify signed step-up assertions.
- `SENA_STEP_UP_MAX_AGE_SECONDS`: max assertion age in seconds (default `300`).
- `SENA_STEP_UP_ISSUER`: required issuer identifier expected in `iss` claim (default `sena-step-up`).
- `SENA_STEP_UP_KEY_ID`: required key identifier expected in `kid` claim (default `default`).

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

These checks enforce separation-of-duties and step-up controls. Signed assertions are bound to caller identity + operation, include explicit expiry, and are replay-detected by `iss:kid:jti` for pilot-safe resistance.

### Signed step-up assertion contract (when enabled)

- Header: `X-Step-Up-Auth: v1.<base64url-json-payload>.<base64url-hmac-sha256-signature>`
- Payload fields:
  - `iss`: must match `SENA_STEP_UP_ISSUER`.
  - `kid`: must match `SENA_STEP_UP_KEY_ID`.
  - `sub`: must match authenticated principal subject.
  - `op`: must equal the sensitive operation (or `*`).
  - `iat`: issued-at epoch seconds, bounded by `SENA_STEP_UP_MAX_AGE_SECONDS`.
  - `exp`: absolute expiry epoch seconds.
  - `jti`: unique token identifier; replay is denied while token is unexpired.
  - `secondary_sub` (required for dual-approval operations): second approver identity bound in signed claims.

### Dual-approval identity binding

- `bundle_promotion` requires two distinct identities:
  1. `sub` (primary approver / authenticated caller),
  2. `secondary_sub` (second approver).
- The same principal cannot satisfy both identities.
- `X-Approver-Id` / `X-Secondary-Approver-Id` are no longer trusted for signed step-up authorization decisions.

## 6) Migration note (caller changes)

Callers that previously sent unsigned `X-Step-Up-Auth: mfa-ok` and free-form approver headers must now:

1. Mint a signed step-up token per sensitive request with `iss/kid/sub/op/iat/exp/jti` (+ `secondary_sub` when dual approval applies).
2. Send `X-Step-Up-Auth` with the signed token.
3. Stop relying on `X-Approver-Id` / `X-Secondary-Approver-Id` for authorization.

Example promotion request (signed step-up):

```bash
curl -fsS -X POST "$SENA_BASE_URL/v1/bundle/promote" \
  -H "x-api-key: $SENA_DEPLOYER_API_KEY" \
  -H "x-step-up-auth: $SENA_STEP_UP_TOKEN" \
  -H "content-type: application/json" \
  -d '{
    "bundle_id": 42,
    "target_lifecycle": "active",
    "promoted_by": "release-bot",
    "promotion_reason": "CAB-1001 approved",
    "validation_artifact": "promotion-validation.json"
  }'
```

## 5) App auth vs policy actor identity

Important distinction:

- **App auth identity**: who is calling the API (`principal.subject`, `principal.role`).
- **Policy identity fields**: data inside evaluation payload (`actor_id`, `actor_role`) used by decision rules.

These are intentionally independent by default to support mediated workflows and service accounts. Enable strict binding with `SENA_ENFORCE_POLICY_ACTOR_IDENTITY=true` when policy actor identity must match JWT subject for evaluation requests.
