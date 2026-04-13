# SENA Cookbook

> **Deprecation notice (default path):** This page is not part of the supported default story. Recipes here are experimental/labs-oriented and indexed from `docs/EXPERIMENTAL_INDEX.md`.

## Experimental: add SENA to a LangChain agent
```python
from sena.integrations.langchain.SenaApprovalCallback import SenaApprovalCallback

callback = SenaApprovalCallback(policy_dir="src/sena/examples/policies")
agent = build_your_langchain_agent(callbacks=[callback])
result = agent.invoke({"input": "Approve vendor payment for 15000"})
print(result)
```

## Labs/demo: deploy as a K8s admission controller
```bash
python examples/k8s_admission_demo/sena_webhook.py
kubectl apply -f examples/k8s_admission_demo/policies/bundle.yaml
kubectl apply -f examples/k8s_admission_demo/policies/k8s_scaling.yaml
```

## Supported utility: verify an audit proof using Python
```python
from sena.audit.verification_service import DailyAuditVerificationService

service = DailyAuditVerificationService(audit_path="./artifacts/audit/audit.jsonl")
print(service.verify_now())
```
