# Supported-path Release Candidate Readiness (2026-04-12)

Scope reviewed: supported Jira + ServiceNow path only (`src/sena/integrations/jira.py`, `src/sena/integrations/servicenow.py`, runtime wiring, and `/v1/integrations/*` API handling).

## What is now strong

- Deterministic, explicit webhook normalization + route-driven evaluation for both connectors.
- Durable outbound reliability model (completion records, dead-letter, replay/manual-redrive) with production startup guards for required persistence and signing controls.
- Signature verification with rotating secret support for both Jira and ServiceNow when secrets are configured.
- Dead-letter capture now stores payload plus digest metadata instead of raw request bodies, and redacts sensitive inbound headers.

## What remains intentionally alpha (bounded)

- Generic webhook mapper and Slack interaction path remain explicitly experimental and not part of supported commitment.
- Allow-all webhook verifier remains available only in `development`; `pilot`/`production` startup fail closed when supported connectors are enabled without secrets.

## Remaining low-severity trust leaks

- Admin/manual-redrive result payloads intentionally preserve operator note text in durable completion records for auditability; this can still include sensitive free text if operators provide it.
- Delivery IDs can still use upstream request identifiers as provided; malformed/low-entropy partner identifiers can reduce forensic quality (not correctness).

## Future work (explicitly wait until after adoption)

- Add optional structured note taxonomy for manual redrive (`reason_code` + optional note) to reduce sensitive free-text usage without removing operator flexibility.
- Add connector-specific delivery-id quality checks (entropy/format warnings) surfaced in reliability summary.
