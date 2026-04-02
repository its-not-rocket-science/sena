# Decision Review Packages

Decision Review Packages convert SENA runtime evaluation traces into a durable, human-reviewable artefact for governance workflows.

## Why this exists

SENA decisions are already deterministic and auditable for runtime enforcement. Decision Review Packages extend that value to:

- **Post-hoc control review** by compliance and risk teams.
- **Escalation handling** for manual approvals and exceptions.
- **Control evidence generation** for audit and external assurance activities.
- **Case-management ingestion** with stable JSON structure and normalized source references.

## Package structure

Each package is emitted as JSON with stable top-level keys:

- `package_schema_version`: explicit package schema version.
- `package_type`: fixed discriminator (`sena.decision_review_package`).
- `package_generated_at`: ISO-8601 timestamp.
- `decision_summary`: decision ID, outcome, action, and summary.
- `rules`: matched/applicable/evaluated rules and conflict IDs.
- `precedence`: precedence explanation and reviewer guidance.
- `facts_and_actor`: actor metadata, decision facts/context, and missing fields.
  - Includes `request_origin` classification:
    - `human`
    - `ai_suggested`
    - `autonomous_tool`
  - AI-suggested requests also carry first-class governance metadata (originating model/system, prompt context ref, requested tool/action, evidence/citations, human owner chain, and risk classification).
- `policy_bundle_metadata`: bundle name/version/lifecycle/schema/integrity metadata.
- `governance_evidence`: normalized missing evidence classes and per-rule evidence gaps for AI-assisted governance controls.
- `audit_identifiers`: request, decision hash, chain hashes, storage sequence IDs.
- `normalized_source_system_references`: normalized source-system IDs and references.

## CLI usage

Generate a review package from a scenario file:

```bash
python -m sena.cli.main src/sena/examples/scenarios/demo_vendor_payment_block_unverified.json --review-package
```

## API usage

Use `POST /v1/evaluate/review-package` with the same payload shape as `POST /v1/evaluate`.

Example request body:

```json
{
  "action_type": "approve_vendor_payment",
  "request_id": "req-123",
  "actor_id": "user-42",
  "actor_role": "finance_analyst",
  "attributes": {
    "amount": 15000,
    "vendor_verified": false
  },
  "facts": {}
}
```

## Governance and audit workflows

Decision Review Packages are designed to support compliance stakeholders by making SENA output:

- **Durable**: deterministic JSON object with explicit schema version.
- **Human-reviewable**: includes summary + precedence explanation + guidance.
- **Case-ready**: includes normalized source references and audit identifiers.
- **Evidence-friendly**: links policy bundle metadata and decision hashes for control attestation.

In short, SENA can now support both runtime control enforcement and downstream governance evidence pipelines.

## Deterministic governance for AI-driven actions

SENA treats AI-assisted actions as a **stricter governed request class**, not as a probabilistic score.

- AI-originated proposals must include deterministic governance metadata before rule evaluation.
- Missing AI governance fields result in deterministic `BLOCKED` outcomes.
- Rules can declare evidence bundles (`required_evidence`) with deterministic `missing_evidence_decision` behavior (`ESCALATE` or `BLOCK`).
- Policy allow/block precedence remains unchanged and does not depend on model confidence.
