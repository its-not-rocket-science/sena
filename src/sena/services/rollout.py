from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    from sena.policy.yaml_support import yaml
except ModuleNotFoundError:  # pragma: no cover
    yaml = None


class RolloutConfigError(ValueError):
    """Raised when rollout configuration is invalid."""


@dataclass(frozen=True)
class RolloutRule:
    business_unit: str | None
    regions: tuple[str, ...]
    mode: str
    policy_bundle: str
    parallel_candidate_bundle: str | None = None


@dataclass(frozen=True)
class RolloutTarget:
    mode: str
    policy_bundle: str
    parallel_candidate_bundle: str | None
    matched_rule_index: int | None


@dataclass(frozen=True)
class RolloutConfig:
    default_mode: str
    default_policy_bundle: str
    default_parallel_candidate_bundle: str | None
    rules: tuple[RolloutRule, ...]

    def resolve(self, *, business_unit: str, region: str) -> RolloutTarget:
        best_score = -1
        best_idx: int | None = None
        best_rule: RolloutRule | None = None

        for idx, rule in enumerate(self.rules):
            bu_match = rule.business_unit is None or rule.business_unit == business_unit
            region_match = not rule.regions or region in rule.regions
            if not bu_match or not region_match:
                continue
            score = (2 if rule.business_unit is not None else 0) + (
                1 if rule.regions else 0
            )
            if score > best_score:
                best_score = score
                best_idx = idx
                best_rule = rule

        if best_rule is None:
            return RolloutTarget(
                mode=self.default_mode,
                policy_bundle=self.default_policy_bundle,
                parallel_candidate_bundle=self.default_parallel_candidate_bundle,
                matched_rule_index=None,
            )

        return RolloutTarget(
            mode=best_rule.mode,
            policy_bundle=best_rule.policy_bundle,
            parallel_candidate_bundle=best_rule.parallel_candidate_bundle,
            matched_rule_index=best_idx,
        )


_ALLOWED_MODES = {"legacy", "sena", "parallel"}


def _validate_mode(value: object) -> str:
    mode = str(value or "").strip().lower()
    if mode not in _ALLOWED_MODES:
        raise RolloutConfigError(
            f"unsupported rollout mode '{value}'. Expected one of {_ALLOWED_MODES}"
        )
    return mode


def _normalize_regions(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RolloutConfigError("rollout rule regions must be a list of strings")
    normalized = tuple(item.strip() for item in value if item.strip())
    return normalized


def load_rollout_config(path: str | Path) -> RolloutConfig:
    payload_text = Path(path).read_text(encoding="utf-8")
    if yaml is not None:
        payload = yaml.safe_load(payload_text)
    else:
        import json

        payload = json.loads(payload_text)
    if not isinstance(payload, dict):
        raise RolloutConfigError("rollout config must be an object")

    default_mode = _validate_mode(payload.get("default_mode", "legacy"))
    default_bundle = str(payload.get("default_policy_bundle") or "legacy:stable")
    default_parallel = payload.get("default_parallel_candidate_bundle")
    if default_parallel is not None:
        default_parallel = str(default_parallel)

    raw_rules = payload.get("rules", [])
    if not isinstance(raw_rules, list):
        raise RolloutConfigError("rollout config rules must be a list")

    parsed_rules: list[RolloutRule] = []
    for idx, entry in enumerate(raw_rules):
        if not isinstance(entry, dict):
            raise RolloutConfigError(f"rule index {idx} must be an object")
        business_unit = entry.get("business_unit")
        if business_unit is not None and not isinstance(business_unit, str):
            raise RolloutConfigError(
                f"rule index {idx} business_unit must be string or null"
            )
        mode = _validate_mode(entry.get("mode", default_mode))
        policy_bundle = str(entry.get("policy_bundle") or default_bundle)
        parallel_bundle = entry.get("parallel_candidate_bundle")
        if parallel_bundle is not None:
            parallel_bundle = str(parallel_bundle)
        if mode == "parallel" and parallel_bundle is None:
            raise RolloutConfigError(
                f"rule index {idx} must set parallel_candidate_bundle for parallel mode"
            )
        parsed_rules.append(
            RolloutRule(
                business_unit=business_unit,
                regions=_normalize_regions(entry.get("regions")),
                mode=mode,
                policy_bundle=policy_bundle,
                parallel_candidate_bundle=parallel_bundle,
            )
        )

    if default_mode == "parallel" and default_parallel is None:
        raise RolloutConfigError(
            "default_parallel_candidate_bundle is required when default_mode=parallel"
        )

    return RolloutConfig(
        default_mode=default_mode,
        default_policy_bundle=default_bundle,
        default_parallel_candidate_bundle=default_parallel,
        rules=tuple(parsed_rules),
    )
