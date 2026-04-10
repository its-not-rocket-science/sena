# Experimental, Labs, and Demo Index

Everything in this index is **explicitly non-supported** unless promoted into the supported path.

## Experimental integration surfaces (evaluation-only)

- Generic webhook: `src/sena/integrations/webhook.py`
- Slack interactions: `src/sena/integrations/slack.py`
- LangChain callback: `src/sena/integrations/langchain/`

## Demo/labs documentation

- `LABS.md`
- `labs/INVESTOR_DEMO.md`
- `labs/INVESTOR_PITCH.md`
- `labs/FUNDRAISING_DECK.md`
- `labs/ENTERPRISE_GAP_ANALYSIS.md`
- `blog/langchain_integration.md`

## Demo example assets

- `../examples/k8s_admission_demo/`
- `../examples/langchain_demo/`

## Historical material

- `archive/legacy_vision.md`

## Promotion rule

Experimental/labs/demo material should be treated as product scope **only after**:
1. code path hardening in `src/sena/*`,
2. deterministic fixtures and tests,
3. inclusion in supported indexes (`README.md`, `docs/INDEX.md`, `examples/README.md`).
