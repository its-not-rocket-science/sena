# Asynchronous execution model

SENA supports asynchronous jobs for long-running endpoints so heavy workflows do not block request-response lifecycles. Job state is now persisted in sqlite and remains queryable across API restarts.

## Slow or unbounded workflows

The following API workflows are most likely to become slow due to payload size, policy volume, or I/O:

- `POST /v1/simulation` (large scenario sets and cross-bundle comparisons).
- `POST /v1/replay/drift` (replay payload size scales with case history).
- `POST /v1/simulation/replay` (audit scan + replay evaluation over historical traffic).
- `GET /v1/audit/verify` and `POST /v1/audit/verify/tree` (large audit chains / proofs).
- Admin dead-letter replay and redrive routes under `/v1/integrations/*/admin/outbound/dead-letter/*`.

Current migration focuses on simulation first while keeping the abstraction reusable for replay and audit verification.

## Job model

Each async job stores durable metadata in the `async_jobs` sqlite table (in `SENA_PROCESSING_SQLITE_PATH`):

- `job_id`
- `status`: `queued | running | succeeded | failed | cancelled | timed_out`
- `submitted_at`, `started_at`, `completed_at`
- `result_ref` (durable reference URI `sqlite://async_jobs/<job_id>`)
- `error` payload (code/message/type/trace)
- `result` payload JSON for succeeded jobs (raw payload can later be externalized while keeping `result_ref`)

Implementation: `InProcessJobManager` in `src/sena/services/async_jobs.py`.

## API endpoints

- `POST /v1/jobs/simulation`: submit simulation as async job.
- `GET /v1/jobs/{job_id}`: poll status (idempotent polling).
- `GET /v1/jobs/{job_id}/result`: fetch result when succeeded.
- `POST /v1/jobs/{job_id}/cancel`: request cancellation.

## Synchronous fast path

`POST /v1/simulation` keeps a synchronous fast path:

- `execution_mode=sync`: always synchronous.
- `execution_mode=auto` (default): synchronous for small requests (`<=25` scenarios), async otherwise.
- `execution_mode=async`: always asynchronous via job queue.

## Timeout and cancellation semantics

- **Timeout:** supported per submitted simulation job via `timeout_seconds`.
- **Cancellation:** best-effort cancellation via `POST /v1/jobs/{job_id}/cancel`.
  - If not yet started, cancellation is immediate.
  - If already running, cancellation is cooperative and final status is marked `cancelled` at completion boundary.

## Restart semantics (operator contract)

- **Terminal jobs (`succeeded`, `failed`, `cancelled`, `timed_out`)**
  - remain queryable after restart through `GET /v1/jobs/{job_id}`.
  - keep their `result_ref` / error metadata.
  - succeeded jobs keep their stored result payload for `GET /v1/jobs/{job_id}/result`.
- **In-flight jobs (`queued`, `running`)**
  - are deterministically marked `failed` during manager startup.
  - receive error code `interrupted_by_restart`.
  - are not auto-resumed (fail-safe behavior to avoid duplicate execution side effects).

This gives deterministic crash recovery while preserving auditability of accepted work.

## Extensibility notes

This design intentionally avoids distributed queue orchestration for now. Production extension points are:

- swap `InProcessJobManager` for durable backend (Redis/SQS/DB queue)
- persist `result_ref` externally (object store)
- add retry policy and per-job type admission controls
