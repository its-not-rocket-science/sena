from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sena.core.enums import RuleDecision, Severity
from sena.core.models import PolicyRule
from sena.policy.validation import PolicyValidationError, validate_rule_payload

try:
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    yaml = None


class PolicyParseError(ValueError):
    pass


def _load_mapping(raw_text: str, source: Path) -> Any:
    if yaml is not None:
        return yaml.safe_load(raw_text)
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise PolicyParseError(
            f"Cannot parse {source}. Install PyYAML or provide JSON-compatible YAML."
        ) from exc


def parse_policy_file(path: str | Path) -> list[PolicyRule]:
    file_path = Path(path)
    raw = _load_mapping(file_path.read_text(), file_path)
    if not isinstance(raw, list):
        raise PolicyParseError(f"policy file {file_path} must contain a list of rules")

    rules: list[PolicyRule] = []
    for item in raw:
        if not isinstance(item, dict):
            raise PolicyParseError("each rule must be a mapping")
        try:
            validate_rule_payload(item)
            rules.append(
                PolicyRule(
                    id=item["id"],
                    description=item["description"],
                    severity=Severity(item["severity"]),
                    inviolable=bool(item["inviolable"]),
                    applies_to=list(item["applies_to"]),
                    condition=dict(item["condition"]),
                    decision=RuleDecision(item["decision"]),
                    reason=item["reason"],
                )
            )
        except (PolicyValidationError, ValueError, TypeError) as exc:
            raise PolicyParseError(f"invalid rule in {file_path}: {exc}") from exc
    return rules


def load_policies_from_dir(path: str | Path) -> list[PolicyRule]:
    base = Path(path)
    all_rules: list[PolicyRule] = []
    for policy_file in sorted(base.glob("*.yaml")):
        all_rules.extend(parse_policy_file(policy_file))
    return all_rules
