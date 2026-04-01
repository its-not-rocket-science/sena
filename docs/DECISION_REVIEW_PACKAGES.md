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
- `policy_bundle_metadata`: bundle name/version/lifecycle/schema/integrity metadata.
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
