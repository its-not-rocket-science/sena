# Performance Baseline (Single Instance)

SENA benchmarks are defined in `benchmarks/bench_evaluate.py` and run in CI via `pytest benchmarks/ --benchmark-only`.

## Measured metrics

- **Evaluations/second**: deterministic policy evaluation throughput.
- **Audit writes/second**: end-to-end evaluate + append-to-audit performance.
- **Merkle proof generation**: proof generation latency for an existing audit tree.

## Expected throughput (single instance, Python 3.11)

These are baseline expectations for regression tracking, not hard SLOs:

- Evaluations: **>= 1,000 evaluations/sec**
- Audit writes: **>= 300 writes/sec**
- Merkle proof generation: **<= 2 ms/proof** for 500-entry trees

CI stores benchmark output in JSON so trend regressions are reviewable over time.
