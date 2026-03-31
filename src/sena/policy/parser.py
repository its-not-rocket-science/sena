from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from sena.core.enums import RuleDecision, Severity
from sena.core.models import PolicyBundleMetadata, PolicyRule
from sena.policy.validation import PolicyValidationError, validate_rule_payload

try:
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    yaml = None


class PolicyParseError(ValueError):
    pass


class BundleManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_name: str = Field(min_length=1)
    version: str | int | float
    owner: str | None = None
    description: str | None = None
    schema_version: str = "1"

    @field_validator("version")
    @classmethod
    def normalize_version(cls, value: str | int | float) -> str:
        return str(value)



def _load_bundle_manifest(base: Path) -> BundleManifest | None:
    for filename in ("bundle.yaml", "bundle.yml", "bundle.json"):
        manifest_path = base / filename
        if manifest_path.exists():
            raw_manifest = _load_mapping(manifest_path.read_text(), manifest_path)
            if not isinstance(raw_manifest, dict):
                raise PolicyParseError(f"bundle manifest {manifest_path} must be a mapping")
            try:
                return BundleManifest.model_validate(raw_manifest)
            except ValidationError as exc:
                raise PolicyParseError(f"invalid bundle manifest {manifest_path}: {exc}") from exc
    return None



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



def _bundle_integrity_digest(files: list[Path]) -> str:
    digest = hashlib.sha256()
    for policy_file in files:
        digest.update(policy_file.name.encode("utf-8"))
        digest.update(policy_file.read_bytes())
    return digest.hexdigest()



def load_policies_from_dir(path: str | Path) -> list[PolicyRule]:
    return load_policy_bundle(path)[0]



def load_policy_bundle(
    path: str | Path,
    bundle_name: str = "default-bundle",
    version: str = "0.1.0-alpha",
) -> tuple[list[PolicyRule], PolicyBundleMetadata]:
    base = Path(path)
    if not base.exists() or not base.is_dir():
        raise PolicyParseError(f"policy directory does not exist or is not a directory: {base}")

    manifest = _load_bundle_manifest(base)

    policy_files: list[Path] = []
    for pattern in ("*.yaml", "*.yml", "*.json"):
        for policy_file in sorted(base.glob(pattern)):
            if policy_file.name in {"bundle.yaml", "bundle.yml", "bundle.json"}:
                continue
            policy_files.append(policy_file)

    if not policy_files:
        raise PolicyParseError(f"no policy files were found in directory: {base}")

    all_rules: list[PolicyRule] = []
    for policy_file in policy_files:
        all_rules.extend(parse_policy_file(policy_file))

    metadata = PolicyBundleMetadata(
        bundle_name=manifest.bundle_name if manifest else bundle_name,
        version=str(manifest.version) if manifest else version,
        loaded_from=str(base.resolve()),
        owner=manifest.owner if manifest else None,
        description=manifest.description if manifest else None,
        schema_version=manifest.schema_version if manifest else "1",
        integrity_sha256=_bundle_integrity_digest(policy_files),
        policy_file_count=len(policy_files),
    )
    return all_rules, metadata
