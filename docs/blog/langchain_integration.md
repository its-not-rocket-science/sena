# Auditing Your AI Agent's Decisions with SENA

LangChain agents are increasingly running production workflows where every tool call can have operational, legal, or financial impact. SENA gives you deterministic policy enforcement before the tool executes, plus tamper-evident audit traces for every decision.

## 5 lines to add an audit trail

```python
from sena.integrations.langchain import SenaApprovalCallback

agent = create_agent(...)
agent.callbacks = [
    SenaApprovalCallback("http://localhost:8000", "enterprise-demo:active")
]
```

When a tool call starts, the callback sends a deterministic evaluation request to SENA. If the outcome is `BLOCKED`, execution fails fast with a `SenaBlockedError`. If allowed, decision identifiers and proof fields are attached to callback metadata for downstream logging and review.

## Why this matters in production

- **Prevent unsafe actions up front:** block destructive or non-compliant tool calls before side effects occur.
- **Deterministic governance:** policy outcomes are explainable and stable under the same inputs.
- **Tamper-evident auditability:** each decision can be independently validated against the audit Merkle root.
- **Lower incident response time:** every decision has a traceable ID and policy context.

## Try it now

1. Run the LangChain refund demo in `examples/langchain_demo/refund_agent.py`.
2. Verify audit proofs with `examples/langchain_demo/verify_refund_audit.py`.
3. Adapt the callback policy bundle to your own tool names and risk controls.

If this is useful, **star the repo** and open an issue with your production use case—we are prioritizing real-world agent governance workflows.
