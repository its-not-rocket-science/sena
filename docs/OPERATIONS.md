# SENA Operations Guide (alpha)

Application versioning: package and FastAPI app version are sourced from `sena.__version__` in `src/sena/__init__.py`.

## Run locally
1. Install dependencies:
   - `pip install -e .[api,dev]`
2. Copy environment template:
   - `cp .env.example .env`
3. Start API:
   - `python -m uvicorn sena.api.app:app --host 0.0.0.0 --port 8000`

## API configuration via environment
- `SENA_POLICY_DIR`: policy bundle directory (required for production correctness)
- `SENA_BUNDLE_NAME`, `SENA_BUNDLE_VERSION`: metadata override fallback
- `SENA_API_KEY_ENABLED=true` + `SENA_API_KEY=<value>`: enables shared-key auth middleware
- `SENA_AUDIT_SINK_JSONL`: optional file path for JSONL audit append sink
- `SENA_LOG_LEVEL`: standard Python logging level

## Health model
- `GET /v1/health`: liveness + loaded bundle metadata
- `GET /v1/ready`: readiness contract (bundle loaded)

## Deployment
### Docker
- `docker build -t sena-api:local .`
- `docker run --env-file .env.example -p 8000:8000 sena-api:local`

### Docker Compose
- `docker compose up --build`

## Supported and unsupported boundaries
Supported product path:
- `src/sena/policy/*`
- `src/sena/engine/*`
- `src/sena/api/*`
- `src/sena/cli/*`

Legacy/historical path (not supported for enterprise use):
- `src/sena/legacy/*`

## What enterprise-ready still does NOT mean (alpha honesty)
- No built-in HA, tenant isolation, or distributed coordinator.
- No native SSO/OIDC and no policy authoring governance UI.
- No formal certification/compliance attestation claims.
