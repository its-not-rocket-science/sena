# Enterprise Security Checklist

Use this checklist during design reviews, release readiness reviews, and recurring security governance reviews.

## Governance and documentation

- [ ] Data flow diagram updated for current architecture and trust boundaries.
- [ ] Threat model reviewed within the last 6 months.
- [ ] Incident response plan reviewed and ownership verified.
- [ ] Breach notification process validated with Legal/Privacy stakeholders.
- [ ] Subprocessors list updated and customer notification obligations assessed.

## Identity, access, and secrets

- [ ] API/admin access follows least privilege.
- [ ] Credential and API key rotation schedule is defined and executed.
- [ ] Privileged access and break-glass events are logged and reviewed.

## Application and data protection

- [ ] Input validation and schema enforcement enabled on ingress APIs.
- [ ] TLS enforced for data in transit.
- [ ] Sensitive fields are redacted/minimized in logs and response payloads.
- [ ] Audit evidence chain verification is scheduled and monitored.

## Vulnerability and patch management

- [ ] Dependency scans run on pull requests and mainline merges.
- [ ] Blocking vulnerability thresholds are enforced in CI.
- [ ] Vulnerability exceptions include owners, expirations, and compensating controls.
- [ ] Patch cadence follows weekly/monthly/quarterly policy.
- [ ] Emergency patch process is documented and tested.

## Detection, response, and recovery

- [ ] Security alerting routes to an on-call path.
- [ ] Incident severity definitions are understood by responders.
- [ ] Forensic evidence retention steps are tested.
- [ ] Post-incident report SLA is met for SEV-1/SEV-2 incidents.

## Verification and assurance

- [ ] `pytest` passes for current codebase state.
- [ ] `ruff check src tests` passes.
- [ ] Replay/drift checks validate deterministic behavior after policy and dependency updates.
