# ServiceNow Change Governance Pack (Canonical Demo)

SENA's primary wedge is deterministic policy control for Jira + ServiceNow approvals. This pack chooses **ServiceNow change approval** as the primary integration and adds **Jira portability checks**.

## Why this is the primary wedge pack

- Current supported integrations are Jira + ServiceNow.
- This pack runs an end-to-end lifecycle with deterministic evidence artifacts.
- It demonstrates governance outcomes relevant to change control, risk, and audit teams.

## Workflow covered end to end

1. Source events are mapped with deterministic ServiceNow routes.
2. Candidate and active bundles are loaded.
3. Simulation shows candidate vs active outcome deltas.
4. Active bundle release manifest is signed and verified.
5. Promotion validation gates release.
6. Runtime events are evaluated and decisions delivered.
7. Audit chain records and verifies deterministic traces.
8. Replay confirms stable outcomes and policy-change drift visibility.
9. Portability examples show shared contract across ServiceNow + Jira.

## Run it

```bash
PYTHONPATH=src python examples/design_partner_reference/run_reference.py
```

Optional guided demo:

```bash
examples/design_partner_reference/demo_15m.sh
```

## Key evidence outputs

- Promotion gate:
  - `examples/design_partner_reference/artifacts/simulation-report.json`
  - `examples/design_partner_reference/artifacts/promotion-validation.json`
- Release signing:
  - `examples/design_partner_reference/artifacts/release-manifest.json`
- Runtime + audit:
  - `examples/design_partner_reference/artifacts/evaluation-results.json`
  - `examples/design_partner_reference/artifacts/audit-chain-verification.json`
- Replay + portability:
  - `examples/design_partner_reference/artifacts/replay-report-stable.json`
  - `examples/design_partner_reference/artifacts/replay-report-policy-update.json`
  - `examples/design_partner_reference/artifacts/normalized-event-examples.json`

## Validation expectations

- **Happy path:** full run succeeds and generates all artifacts.
- **Malformed payloads:** deterministic integration errors for missing event type / required fields.
- **Replay determinism:** stable replay reports zero changed outcomes.
- **Policy update visibility:** simulation and replay update reports show emergency privileged no-chain tightening.

See `examples/design_partner_reference/operator_runbook.md` for operator procedures.
