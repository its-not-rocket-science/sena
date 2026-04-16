# Asynchronous execution model

SENA now supports in-process asynchronous jobs for long-running endpoints so heavy workflows do not block request-response lifecycles.

## Slow or unbounded workflows

The following API workflows are most likely to become slow due to payload size, policy volume, or I/O:

- `POST /v1/simulation` (large scenario sets and cross-bundle comparisons).
- `POST /v1/replay/drift` (replay payload size scales with case history).
- `POST /v1/simulation/replay` (audit scan + replay evaluation over historical traffic).
- `GET /v1/audit/verify` and `POST /v1/audit/verify/tree` (large audit chains / proofs).
- Admin dead-letter replay and redrive routes under `/v1/integrations/*/admin/outbound/dead-letter/*`.

Current migration focuses on simulation first while keeping the abstraction reusable for replay and audit verification.

## Job model

Each async job stores:

- `job_id`
- `status`: `queued | running | succeeded | failed | cancelled | timed_out`
- `submitted_at`, `started_at`, `completed_at`
- `result_ref` (currently in-memory URI `memory://jobs/<job_id>/result`)
- `error` payload (code/message/type/trace)

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

## Extensibility notes

This design intentionally avoids distributed infrastructure for now. Production extension points are:

- swap `InProcessJobManager` for durable backend (Redis/SQS/DB queue)
- persist `result_ref` externally (object store)
- add retry policy and per-job type admission controls
