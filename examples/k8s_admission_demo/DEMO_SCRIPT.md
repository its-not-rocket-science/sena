# 5-Minute Investor Demo Script: Kubernetes Admission Controller + SENA

## 0) Prep (30s)

```bash
make demo-k8s
```

What the audience should see:
- AI suggests scaling to 10 replicas.
- SENA blocks the deployment change (`max replicas = 5`).
- A Merkle proof is attached to the admission decision.
- External verification succeeds.
- Tampering fails verification.

## 1) Show AI suggestion (45s)

```bash
python examples/k8s_admission_demo/ai_agent_simulator.py
```

Narration: "Our agent proposes a scale-up to handle traffic."

## 2) Show the policy gate (60s)

Policy to highlight: `examples/k8s_admission_demo/policies/k8s_scaling.yaml`
- `k8s_block_ai_scale_above_budget_cap`
- Inviolable control
- AI-suggested + replicas > 5 => BLOCK

Narration: "This is deterministic guardrail logic that cannot be bypassed silently."

## 3) Run admission flow and show block (75s)

```bash
python examples/k8s_admission_demo/verify_demo.py
```

Expected output includes:
- `"allowed": false`
- `SENA blocked AI-suggested scale change: max replicas = 5.`
- annotation `sena.audit.proof` with Merkle material

Narration: "This decision is blocked and audit-linked in real time."

## 4) Show independent proof verification (45s)

`verify_demo.py` prints:
- `Proof verified: True`

Narration: "Any auditor can verify this decision without trusting SENA blindly."

## 5) Show tampering failure (45s)

`verify_demo.py` prints:
- `Tampered proof verified: False`

Narration: "If records are altered, cryptographic verification breaks immediately."

## 6) Metrics dashboard (45s)

For full stack UI:

```bash
docker compose -f examples/k8s_admission_demo/docker-compose-demo.yml up --build
```

Open:
- Grafana: http://localhost:3000
- Prometheus: http://localhost:9090

Dashboard: **SENA Investor Demo**
- Panel: `Decision Outcomes (/v1/evaluate)`

Narration: "Leadership gets operational visibility on how often AI changes are approved vs blocked."
