# 5-Minute Kubernetes Demo Script (Experimental)

> **Status note:** this is an experimental demo script used to showcase mechanics. It is not the primary supported integration narrative.

## 0) Prep (30s)

```bash
make demo-k8s
```

What the audience should see:
- AI suggests scaling to 10 replicas.
- SENA blocks the deployment change (`max replicas = 5`).
- Proof material is attached to the admission decision.
- External verification succeeds.
- Tampering fails verification.

## 1) Show AI suggestion (45s)

```bash
python examples/k8s_admission_demo/ai_agent_simulator.py
```

## 2) Show the policy gate (60s)

Policy to highlight: `examples/k8s_admission_demo/policies/k8s_scaling.yaml`
- `k8s_block_ai_scale_above_budget_cap`
- inviolable control
- AI-suggested + replicas > 5 => BLOCK

## 3) Run admission flow and show block (75s)

```bash
python examples/k8s_admission_demo/verify_demo.py
```

Expected output includes:
- `"allowed": false`
- `SENA blocked AI-suggested scale change: max replicas = 5.`

## 4) Show independent proof verification (45s)

`verify_demo.py` prints:
- `Proof verified: True`

## 5) Show tampering failure (45s)

`verify_demo.py` prints:
- `Tampered proof verified: False`

## 6) Metrics dashboard (optional, 45s)

```bash
docker compose -f examples/k8s_admission_demo/docker-compose-demo.yml up --build
```

Open:
- Grafana: http://localhost:3000
- Prometheus: http://localhost:9090
