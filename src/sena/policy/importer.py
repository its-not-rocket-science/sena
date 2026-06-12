from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sena.core.enums import RuleDecision, Severity

try:
    from sena.policy.yaml_support import yaml
except ModuleNotFoundError:  # pragma: no cover
    yaml = None


class PolicyImportError(ValueError):
    """Raised when a legacy policy payload cannot be converted deterministically."""


@dataclass(frozen=True)
class PolicyImportResult:
    source_format: str
    source_rule_count: int
    output_rule_count: int
    output_bundle_dir: str
    output_files: list[str]


def _load_mapping(path: Path) -> Any:
    raw = path.read_text(encoding="utf-8")
    if yaml is not None:
        return yaml.safe_load(raw)
    import json

    return json.loads(raw)


def _normalize_severity(value: object) -> str:
    if value is None:
        return Severity.MEDIUM.value
    raw = str(value).strip().lower()
    mapping = {
        "low": Severity.LOW.value,
        "medium": Severity.MEDIUM.value,
        "med": Severity.MEDIUM.value,
        "high": Severity.HIGH.value,
        "critical": Severity.CRITICAL.value,
    }
    if raw in mapping:
        return mapping[raw]
    raise PolicyImportError(f"unsupported severity '{value}'")


def _normalize_decision(value: object) -> str:
    if value is None:
        raise PolicyImportError("legacy decision is required")
    raw = str(value).strip().lower()
    mapping = {
        "allow": RuleDecision.ALLOW.value,
        "approve": RuleDecision.ALLOW.value,
        "approved": RuleDecision.ALLOW.value,
        "block": RuleDecision.BLOCK.value,
        "deny": RuleDecision.BLOCK.value,
        "blocked": RuleDecision.BLOCK.value,
        "escalate": RuleDecision.ESCALATE.value,
        "review": RuleDecision.ESCALATE.value,
        "manual_review": RuleDecision.ESCALATE.value,
    }
    if raw in mapping:
        return mapping[raw]
    raise PolicyImportError(f"unsupported decision '{value}'")


def _normalize_applies_to(value: object) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list) and value and all(
        isinstance(item, str) and item.strip() for item in value
    ):
        return [str(item).strip() for item in value]
    raise PolicyImportError("legacy rule must provide non-empty action/applies_to")


def _normalize_condition(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        normalized = dict(value)
        if "all" in normalized and "and" not in normalized:
            normalized["and"] = normalized.pop("all")
        if "any" in normalized and "or" not in normalized:
            normalized["or"] = normalized.pop("any")
        if "equals" in normalized and "eq" not in normalized:
            normalized["eq"] = normalized.pop("equals")
        if "not_equals" in normalized and "ne" not in normalized:
            normalized["ne"] = normalized.pop("not_equals")
        if "and" in normalized and isinstance(normalized["and"], list):
            normalized["and"] = [
                _normalize_condition(item) if isinstance(item, dict) else item
                for item in normalized["and"]
            ]
        if "or" in normalized and isinstance(normalized["or"], list):
            normalized["or"] = [
                _normalize_condition(item) if isinstance(item, dict) else item
                for item in normalized["or"]
            ]
        if "not" in normalized and isinstance(normalized["not"], dict):
            normalized["not"] = _normalize_condition(normalized["not"])
        return normalized
    raise PolicyImportError("legacy rule must include object condition/when")


def _convert_rule(entry: dict[str, Any], index: int) -> dict[str, Any]:
    rule_id = entry.get("id") or entry.get("policy_id") or f"imported_rule_{index}"
    description = entry.get("description") or entry.get("name") or str(rule_id)

    applies_to_raw = entry.get("applies_to", entry.get("action"))
    decision_raw = entry.get("decision", entry.get("outcome"))
    condition_raw = entry.get("condition", entry.get("when"))
    inviolable = bool(entry.get("inviolable", entry.get("hard_block", False)))

    return {
        "id": str(rule_id),
        "description": str(description),
        "severity": _normalize_severity(entry.get("severity")),
        "inviolable": inviolable,
        "applies_to": _normalize_applies_to(applies_to_raw),
        "condition": _normalize_condition(condition_raw),
        "decision": _normalize_decision(decision_raw),
        "reason": str(entry.get("reason") or entry.get("justification") or "Imported policy rule"),
    }


def _detect_legacy_rules(payload: Any) -> tuple[str, list[dict[str, Any]]]:
    if isinstance(payload, list):
        if not all(isinstance(item, dict) for item in payload):
            raise PolicyImportError("legacy list payload must contain only objects")
        return "list", [dict(item) for item in payload]

    if isinstance(payload, dict):
        if isinstance(payload.get("policies"), list):
            rules = payload["policies"]
            if not all(isinstance(item, dict) for item in rules):
                raise PolicyImportError("policies[] must contain only objects")
            return "legacy_object", [dict(item) for item in rules]
        if isinstance(payload.get("rules"), list):
            rules = payload["rules"]
            if not all(isinstance(item, dict) for item in rules):
                raise PolicyImportError("rules[] must contain only objects")
            return "legacy_object", [dict(item) for item in rules]

    raise PolicyImportError(
        "unsupported legacy payload. Expected list[rule] or {policies:[...]} / {rules:[...]}"
    )


def import_legacy_policy_file(
    *,
    source_path: str | Path,
    output_dir: str | Path,
    bundle_name: str,
    bundle_version: str,
    owner: str | None = None,
    description: str | None = None,
) -> PolicyImportResult:
    source = Path(source_path)
    if not source.exists() or not source.is_file():
        raise PolicyImportError(f"source policy file does not exist: {source}")

    source_payload = _load_mapping(source)
    source_format, legacy_rules = _detect_legacy_rules(source_payload)
    converted = [_convert_rule(rule, idx) for idx, rule in enumerate(legacy_rules, start=1)]

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    policy_filename = f"{source.stem}_imported.yaml"
    policy_path = destination / policy_filename
    bundle_path = destination / "bundle.yaml"

    if yaml is None:
        raise PolicyImportError("PyYAML is required to write imported policy bundles")

    bundle_payload: dict[str, Any] = {
        "bundle_name": bundle_name,
        "version": str(bundle_version),
        "lifecycle": "draft",
        "schema_version": "1",
    }
    if owner:
        bundle_payload["owner"] = owner
    if description:
        bundle_payload["description"] = description

    bundle_path.write_text(yaml.safe_dump(bundle_payload, sort_keys=False), encoding="utf-8")
    policy_path.write_text(yaml.safe_dump(converted, sort_keys=False), encoding="utf-8")

    return PolicyImportResult(
        source_format=source_format,
        source_rule_count=len(legacy_rules),
        output_rule_count=len(converted),
        output_bundle_dir=str(destination),
        output_files=[bundle_path.name, policy_path.name],
    )
