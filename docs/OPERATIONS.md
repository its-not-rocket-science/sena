# SENA Operations Guide (alpha)

Application versioning: package and FastAPI app version are sourced from `sena.__version__` in `src/sena/__init__.py`.

## Run locally
1. Install dependencies:
   - `pip install -e .[api,dev]`
2. Optionally export runtime settings (defaults shown):
   - `export SENA_API_HOST=0.0.0.0`
   - `export SENA_API_PORT=8000`
   - `export SENA_POLICY_DIR=src/sena/examples/policies`
   - `export SENA_BUNDLE_NAME=enterprise-compliance-controls`
   - `export SENA_BUNDLE_VERSION=2026.03`
3. Start API:
   - `python -m uvicorn sena.api.app:app --host 0.0.0.0 --port 8000`

## API configuration via environment
- `SENA_API_HOST`, `SENA_API_PORT`: host/port binding for deployment wrappers
- `SENA_POLICY_DIR`: policy bundle directory (defaults to `src/sena/examples/policies`)
- `SENA_BUNDLE_NAME`, `SENA_BUNDLE_VERSION`: metadata override fallback (default demo bundle metadata)
- `SENA_API_KEY_ENABLED=true` + `SENA_API_KEY=<value>`: enables shared-key auth middleware
- `SENA_AUDIT_SINK_JSONL`: optional file path for JSONL audit append sink
- `SENA_LOG_LEVEL`: standard Python logging level

## Health model
- `GET /v1/health`: liveness + loaded bundle metadata
- `GET /v1/ready`: readiness contract (bundle loaded)
- `GET /v1/bundle`: loaded bundle metadata
- `GET /v1/bundle/inspect`: bundle/rule coverage summary
- `POST /v1/evaluate`: single evaluation
- `POST /v1/evaluate/batch`: batch evaluation
- `POST /v1/simulation`: baseline/candidate scenario simulation
- `POST /v1/bundle/diff`: rule-set diff
- `POST /v1/bundle/promotion/validate`: lifecycle promotion checks
- `GET /v1/audit/verify`: tamper-evident audit verification

## Deployment
### Docker
- `docker build -t sena-api:local .`
- `docker run -e SENA_POLICY_DIR=src/sena/examples/policies -p 8000:8000 sena-api:local`

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
