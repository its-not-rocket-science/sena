from __future__ import annotations

from pathlib import Path

import pytest

from sena.audit.merkle import build_merkle_tree, get_proof
from sena.core.models import ActionProposal
from sena.engine.evaluator import PolicyEvaluator
from sena.policy.parser import load_policy_bundle
from sena.services.audit_service import AuditService


def _build_evaluator() -> PolicyEvaluator:
    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    return PolicyEvaluator(rules=rules, policy_bundle=metadata)


def _proposal() -> ActionProposal:
    return ActionProposal(
        action_type="approve_vendor_payment",
        request_id="bench-1",
        actor_id="bench-user",
        actor_role="finance_analyst",
        attributes={"amount": 1500, "vendor_verified": False},
    )


def test_bench_evaluations_per_second(benchmark: pytest.BenchmarkFixture) -> None:
    evaluator = _build_evaluator()
    proposal = _proposal()
    benchmark(lambda: evaluator.evaluate(proposal, {}))


def test_bench_audit_writes_per_second(tmp_path: Path, benchmark: pytest.BenchmarkFixture) -> None:
    evaluator = _build_evaluator()
    proposal = _proposal()
    audit = AuditService(str(tmp_path / "bench-audit.jsonl"))

    def _write_once() -> None:
        trace = evaluator.evaluate(proposal, {})
        assert trace.audit_record is not None
        audit.append_record(trace.audit_record.__dict__)

    benchmark(_write_once)


def test_bench_merkle_proof_generation(benchmark: pytest.BenchmarkFixture) -> None:
    entries = [
        {"decision_id": f"dec-{index}", "decision_hash": f"hash-{index}", "outcome": "BLOCKED"}
        for index in range(500)
    ]
    tree = build_merkle_tree(entries)
    benchmark(lambda: get_proof(tree, 250))
