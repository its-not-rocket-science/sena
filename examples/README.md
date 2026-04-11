# Examples Index (Supported Path First)

This directory intentionally keeps the **supported operator path** narrow and puts non-supported material in a clearly separate section.

## Supported examples (default)

These are the only examples that should be used for design-partner and production-adjacent workflows:

1. `design_partner_reference/` — canonical Jira + ServiceNow governance pack (normalization, promotion gates, replay, audit evidence).
2. `gated_promotion_flow.sh` — focused CLI promotion-gate walkthrough against the supported policy lifecycle.
3. `basic_usage.py` — minimal evaluator invocation using the supported policy/runtime surface.

### Supported run commands

```bash
PYTHONPATH=src python examples/basic_usage.py
PYTHONPATH=src python examples/design_partner_reference/run_reference.py
bash examples/gated_promotion_flow.sh
```

## Compatibility fixture (not a standalone story)

- `simulation_scenarios.json` — fixture consumed by `gated_promotion_flow.sh`; keep aligned with supported promotion-gate semantics.

## Experimental / labs demos (non-supported)

The following are intentionally **not** product commitments and should not be used to represent supported scope:

- `k8s_admission_demo/` — exploratory Kubernetes admission demo.
- `langchain_demo/` — exploratory LangChain callback demo.

If you are updating docs or onboarding material, always anchor on the supported section above first.
