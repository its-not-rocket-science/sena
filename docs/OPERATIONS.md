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
- `SENA_API_KEY_ENABLED=true` + one of:
  - `SENA_API_KEY=<value>` (single-key mode; key role defaults to `admin`)
  - `SENA_API_KEYS=<key:role,...>` (RBAC mode; roles: `admin`, `policy_author`, `evaluator`)
- Startup fails fast on misconfiguration:
  - `SENA_POLICY_DIR` must exist when `SENA_POLICY_STORE_BACKEND=filesystem`
  - loaded bundle must resolve to a non-empty rule set
  - `SENA_API_KEY` cannot be set unless `SENA_API_KEY_ENABLED=true`
  - `SENA_API_KEYS` cannot be set unless `SENA_API_KEY_ENABLED=true`
  - `SENA_API_KEY` and `SENA_API_KEYS` are mutually exclusive
  - `SENA_RUNTIME_MODE=production` requires `SENA_API_KEY_ENABLED=true`
- `SENA_RATE_LIMIT_REQUESTS`, `SENA_RATE_LIMIT_WINDOW_SECONDS`: fixed-window request budget (per API key when provided, otherwise per client host)
- `SENA_REQUEST_MAX_BYTES`: maximum request payload size in bytes (`413` when exceeded)
- `SENA_REQUEST_TIMEOUT_SECONDS`: request processing timeout in seconds (`504` when exceeded)
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
- `GET /metrics`: Prometheus metrics (`request_count`, `decision_outcome_count`, `evaluation_latency`)

RBAC endpoint groups when `SENA_API_KEYS` is used:
- `admin`: all endpoints
- `policy_author`: `POST /v1/bundle/register`, `POST /v1/bundle/promote`, `POST /v1/bundle/diff`, `POST /v1/bundle/promotion/validate`
- `evaluator`: `POST /v1/evaluate`, `POST /v1/evaluate/batch`, `POST /v1/simulation`, `POST /v1/integrations/webhook`, `POST /v1/integrations/slack/interactions`

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
