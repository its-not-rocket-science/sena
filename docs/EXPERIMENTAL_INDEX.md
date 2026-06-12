# Experimental, Labs, and Demo Index (Non-default)

Everything in this index is explicitly non-supported unless promoted into `README.md` + `docs/INDEX.md`.

## Experimental integration surfaces (evaluation-only)

- Generic webhook: `src/sena/integrations/webhook.py`
- Slack interactions: `src/sena/integrations/slack.py`
- LangChain callback: `src/sena/integrations/langchain/`
- Cookbook recipes with experimental scope: `COOKBOOK.md`

## Labs/demo docs and collateral

- `LABS.md`
- `labs/INVESTOR_DEMO.md`
- `labs/INVESTOR_PITCH.md`
- `labs/FUNDRAISING_DECK.md`
- `labs/ENTERPRISE_GAP_ANALYSIS.md`
- `blog/langchain_integration.md`

## Demo example assets

- `../examples/k8s_admission_demo/`
- `../examples/langchain_demo/`

## Legacy/historical docs

- `archive/legacy_vision.md`
- `THIRTY_DAY_WEDGE_PLAN.md`

## Promotion rule

A non-default item is promoted to supported only after:
1. code-path hardening in supported modules,
2. deterministic fixtures + tests,
3. inclusion in default indexes (`README.md`, `docs/INDEX.md`, `examples/README.md`).
