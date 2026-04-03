# SENA Cookbook

## Add SENA to a LangChain agent in 5 lines
```python
from sena.integrations.langchain.SenaApprovalCallback import SenaApprovalCallback

callback = SenaApprovalCallback(policy_dir="src/sena/examples/policies")
agent = build_your_langchain_agent(callbacks=[callback])
result = agent.invoke({"input": "Approve vendor payment for 15000"})
print(result)
```

## Deploy SENA as a K8s admission controller
```bash
python examples/k8s_admission_demo/sena_webhook.py
kubectl apply -f examples/k8s_admission_demo/policies/bundle.yaml
kubectl apply -f examples/k8s_admission_demo/policies/k8s_scaling.yaml
```

## Verify an audit proof using Python
```python
from sena.audit.verification_service import DailyAuditVerificationService

service = DailyAuditVerificationService(audit_path="./artifacts/audit/audit.jsonl")
print(service.verify_now())
```

## Integrate SENA with an existing Jira workflow
```python
from sena.integrations.jira import JiraWebhookProcessor

processor = JiraWebhookProcessor(mapping_config_path="examples/design_partner_reference/integration/jira_mapping.yaml")
result = processor.process_event(headers=jira_headers, payload=jira_payload, raw_body=raw_body)
print(result)
```
