from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sena.core.models import ActionProposal
from sena.engine.evaluator import PolicyEvaluator
from sena.policy.parser import PolicyParseError, load_policy_bundle

try:
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    yaml = None


class PolicyTestRunnerError(ValueError):
    """Raised when policy test manifests are malformed."""


@dataclass(frozen=True)
class PolicyTestCase:
    name: str
    input: dict[str, Any]
    expected: str


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PolicyTestRunnerError(f"Failed to read test manifest {path}: {exc}") from exc

    if yaml is not None:
        payload = yaml.safe_load(raw)
    else:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PolicyTestRunnerError(
                f"Failed to parse {path}; install PyYAML or provide JSON"
            ) from exc
    if not isinstance(payload, dict):
        raise PolicyTestRunnerError("Test manifest root must be an object")
    return payload


def _parse_cases(payload: dict[str, Any]) -> list[PolicyTestCase]:
    tests = payload.get("tests")
    if not isinstance(tests, list) or not tests:
        raise PolicyTestRunnerError("Test manifest requires non-empty 'tests' list")

    cases: list[PolicyTestCase] = []
    for index, item in enumerate(tests, start=1):
        if not isinstance(item, dict):
            raise PolicyTestRunnerError(f"Test at index {index} must be an object")
        name = str(item.get("name") or f"test_{index}")
        raw_input = item.get("input")
        expected = item.get("expected")
        if not isinstance(raw_input, dict):
            raise PolicyTestRunnerError(f"Test '{name}' input must be an object")
        if not isinstance(expected, str) or not expected.strip():
            raise PolicyTestRunnerError(f"Test '{name}' expected must be non-empty string")
        cases.append(
            PolicyTestCase(name=name, input=raw_input, expected=expected.strip().upper())
        )
    return cases


def run_policy_tests(*, bundle_path: str | Path, tests_path: str | Path) -> dict[str, Any]:
    try:
        rules, metadata = load_policy_bundle(bundle_path)
    except PolicyParseError as exc:
        raise PolicyTestRunnerError(f"Policy test setup failed: {exc}") from exc

    manifest = _load_manifest(Path(tests_path))
    cases = _parse_cases(manifest)
    evaluator = PolicyEvaluator(rules, policy_bundle=metadata)

    failures: list[dict[str, Any]] = []
    for case in cases:
        action_type = case.input.get("action") or case.input.get("action_type")
        if not isinstance(action_type, str) or not action_type.strip():
            raise PolicyTestRunnerError(
                f"Test '{case.name}' input must include non-empty 'action' or 'action_type'"
            )
        proposal = ActionProposal(
            action_type=action_type,
            request_id=case.input.get("request_id"),
            actor_id=case.input.get("actor_id"),
            actor_role=case.input.get("actor_role"),
            attributes={
                key: value
                for key, value in case.input.items()
                if key
                not in {"action", "action_type", "request_id", "actor_id", "actor_role", "facts"}
            },
        )
        facts = case.input.get("facts", {})
        if not isinstance(facts, dict):
            raise PolicyTestRunnerError(f"Test '{case.name}' facts must be an object")
        trace = evaluator.evaluate(proposal, facts)
        actual = trace.outcome.value
        if actual != case.expected:
            failures.append(
                {
                    "name": case.name,
                    "expected": case.expected,
                    "actual": actual,
                    "diff": {
                        "outcome": {"expected": case.expected, "actual": actual},
                        "summary": trace.summary,
                    },
                }
            )

    return {
        "bundle": {
            "bundle_name": metadata.bundle_name,
            "version": metadata.version,
            "path": str(Path(bundle_path)),
        },
        "tests": len(cases),
        "failures": len(failures),
        "passed": len(cases) - len(failures),
        "results": failures,
    }
