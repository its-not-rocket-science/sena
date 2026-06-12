# Enterprise Security Artifact: Data Flow Diagram and Threat Model

## Purpose
This document defines SENA's text-form data flow diagram (DFD) and a STRIDE-oriented threat model for enterprise security reviews.

## System context and trust boundaries

- **TB1: External callers → SENA API** (`/v1/*`), crossing internet/private ingress controls.
- **TB2: SENA API/process → policy bundle + config storage**, crossing application-to-storage permissions.
- **TB3: SENA API/process → audit log/archive storage**, crossing immutable evidence boundaries.
- **TB4: SENA → third-party integrations** (Jira, ServiceNow, optional webhooks), crossing partner network boundaries.
- **TB5: SENA admin/read APIs → operators/auditors**, crossing privileged access boundaries.

## Text-form data flow diagram

```text
[External Systems]
  |  (A) API Requests / Webhooks
  v
+---------------------------+
| API Gateway / Ingress     |
| AuthN/AuthZ, rate limits  |
+------------+--------------+
             |
             | (B) normalized request context
             v
+---------------------------+         +---------------------------+
| SENA API + Decision Engine|<------->| Policy Bundle Store       |
| - parse/validate          |   (C)   | versioned signed bundles  |
| - deterministic evaluate  |         +---------------------------+
| - exceptions overlay      |
+------------+--------------+
             |
             | (D) decision result + trace
             v
+---------------------------+         +---------------------------+
| Audit Chain Writer        |-------->| Audit Log/Archive Storage |
| hash-linked append-only   |   (E)   | JSONL + verification data |
+------------+--------------+         +---------------------------+
             |
             | (F) response payload
             v
[Callers / Integrations (Jira, ServiceNow, internal systems)]

Privileged/admin read paths:
[Security/Ops/Auditors] --(G)--> [/v1/admin/*, /v1/audit/verify, replay endpoints]
```

### Data classifications by flow

- **(A)/(B):** Request metadata, actor identity attributes, workflow/context fields (may include confidential data).
- **(C):** Policy bundles, schema metadata, promotion evidence (integrity-sensitive).
- **(D)/(E):** Decision outputs, evidence traces, hashes, chain links (integrity + retention critical).
- **(F):** Policy decision outcome + evidence excerpt (confidentiality constrained by caller permissions).
- **(G):** Privileged operational/audit telemetry (strict least privilege + full auditability required).

## Threat model (STRIDE)

| Asset/Flow | Threat (STRIDE) | Example attack | Primary controls | Detection/response |
|---|---|---|---|---|
| API ingress (A) | Spoofing | Stolen API key used for decision calls | API key rotation, tenant scoping, network ACLs, mTLS where available | Auth failure anomaly alerts, key revocation runbook |
| Request payloads (B) | Tampering | Payload manipulation in transit | TLS 1.2+, signed transport perimeter, input validation | WAF/API gateway logs + schema reject metrics |
| Decision execution | Repudiation | Caller disputes who initiated decision | Request IDs, signed/hashed audit records, actor attribution fields | Deterministic replay + audit verification |
| Policy bundle store (C) | Tampering/EoP | Unauthorized policy change bypassing review | Promotion validation gates, change approval workflow, least-privilege write access | Bundle diff monitoring + promotion attestation review |
| Decision engine | Information disclosure | Excess context leaked in response | Response minimization, PII redaction, role-based explanation views | DLP review and response payload audits |
| Audit chain (D/E) | Tampering | Deleting/modifying historical evidence | Append-only hash-linked chain, archive immutability, verification endpoint | Scheduled chain verification + incident trigger on failure |
| API/service resources | DoS | Flooding evaluate/replay endpoints | Rate limits, request quotas, async offload for heavy jobs | SLO/error budget alerts + autoscaling/manual mitigation |
| Admin/audit endpoints (G) | EoP/Info disclosure | Privilege escalation to read sensitive payloads | RBAC, separation of duties, legal hold controls, break-glass approvals | Admin access logs, periodic entitlement reviews |
| Integration webhooks | Spoofing/Tampering | Forged Jira/ServiceNow callback | Shared secret validation, source allowlists, signature validation | Webhook signature failure alerts |
| Supply chain | Tampering | Vulnerable or malicious dependency introduced | Locked dependency policy + dependency scanning + patch SLAs | CI scan gates + vulnerability exception workflow |

## High-priority abuse cases and treatment

1. **Unauthorized policy promotion**
   - Risk: malicious control weakening affects many decisions.
   - Treatment: enforce promotion validation + attestation requirements; deny active promotion when required evidence is missing.

2. **Evidence chain integrity break**
   - Risk: loss of non-repudiation for audits/incidents.
   - Treatment: treat failed chain verification as a P1 security incident; activate incident response and preserve forensic copies.

3. **Data overexposure in explanation/admin endpoints**
   - Risk: unintended disclosure of sensitive decision context.
   - Treatment: analyst/auditor view separation, scoped data access APIs, legal hold governance, periodic access review.

## Security requirements traceability (minimum set)

- Deterministic replay capability for incident and dispute handling.
- Immutable/auditable evidence chain verification.
- Least-privilege access for policy, admin, and audit operations.
- Logged and reviewable privileged operations.
- Documented incident response and breach notification workflow.
- Continuous vulnerability/dependency management.
