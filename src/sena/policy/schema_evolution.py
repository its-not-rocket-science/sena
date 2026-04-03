from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from sena import __version__ as SENA_VERSION

try:
    from sena.policy.yaml_support import yaml
except ModuleNotFoundError:  # pragma: no cover
    yaml = None

SCHEMA_VERSION_V1 = "1"
SCHEMA_VERSION_V2 = "2"
CURRENT_BUNDLE_SCHEMA_VERSION = SCHEMA_VERSION_V2
MIN_SUPPORTED_BUNDLE_SCHEMA_VERSION = SCHEMA_VERSION_V1

class PolicySchemaError(ValueError):
    pass

@dataclass(frozen=True)
class VersionRange:
    min_inclusive: str | None = None
    max_inclusive: str | None = None

@dataclass(frozen=True)
class CompatibilityReport:
    compatible: bool
    errors: list[str]
    warnings: list[str]

@dataclass(frozen=True)
class MigrationChange:
    file: str
    description: str
    before: str
    after: str

@dataclass(frozen=True)
class MigrationReport:
    source_schema_version: str
    target_schema_version: str
    changed_files: list[str]
    changes: list[MigrationChange]
    warnings: list[str] = field(default_factory=list)

@dataclass(frozen=True)
class BundleMigrationResult:
    report: MigrationReport
    applied: bool

def normalize_schema_version(value: str | int | float | None) -> str:
    if value is None:
        return SCHEMA_VERSION_V1
    normalized = str(value).strip()
    if not normalized:
        return SCHEMA_VERSION_V1
    if normalized not in {SCHEMA_VERSION_V1, SCHEMA_VERSION_V2}:
        raise PolicySchemaError(f"unsupported bundle schema version '{normalized}'")
    return normalized

def _parse_version(version: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", version)
    if not numbers:
        return (0,)
    return tuple(int(n) for n in numbers)

def _is_version_less(a: str, b: str) -> bool:
    return _parse_version(a) < _parse_version(b)

def _is_version_greater(a: str, b: str) -> bool:
    return _parse_version(a) > _parse_version(b)

def _render_payload(path: Path, payload: object) -> str:
    if path.suffix.lower() == ".json":
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if yaml is None:
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"
    return yaml.safe_dump(payload, sort_keys=False)

def _read_mapping(path: Path) -> object:
    raw_text = path.read_text()
    if yaml is not None:
        return yaml.safe_load(raw_text)
    return json.loads(raw_text)

def _diff(before: str, after: str, file: str) -> str:
    lines = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=f"a/{file}",
        tofile=f"b/{file}",
        lineterm="",
    )
    return "\n".join(lines)

def evaluate_bundle_compatibility(
    *,
    schema_version: str,
    runtime_version: str = SENA_VERSION,
    compatibility: VersionRange | None = None,
) -> CompatibilityReport:
    errors: list[str] = []
    warnings: list[str] = []
    normalized = normalize_schema_version(schema_version)

    if _is_version_less(normalized, MIN_SUPPORTED_BUNDLE_SCHEMA_VERSION):
        errors.append(
            f"bundle schema version {normalized} is older than minimum supported "
            f"{MIN_SUPPORTED_BUNDLE_SCHEMA_VERSION}"
        )
    if _is_version_greater(normalized, CURRENT_BUNDLE_SCHEMA_VERSION):
        errors.append(
            f"bundle schema version {normalized} is newer than runtime-supported "
            f"{CURRENT_BUNDLE_SCHEMA_VERSION}"
        )

    if normalized == SCHEMA_VERSION_V1:
        warnings.append(
            "bundle schema version 1 is deprecated and will be removed in a future release; "
            "migrate to schema version 2"
        )

    if compatibility:
        if compatibility.min_inclusive and _is_version_less(
            runtime_version, compatibility.min_inclusive
        ):
            errors.append(
                f"runtime version {runtime_version} is below manifest minimum "
                f"{compatibility.min_inclusive}"
            )
        if compatibility.max_inclusive and _is_version_greater(
            runtime_version, compatibility.max_inclusive
        ):
            errors.append(
                f"runtime version {runtime_version} is above manifest maximum "
                f"{compatibility.max_inclusive}"
            )

    return CompatibilityReport(compatible=not errors, errors=errors, warnings=warnings)

def migrate_bundle(
    policy_dir: Path,
    *,
    target_schema_version: str = CURRENT_BUNDLE_SCHEMA_VERSION,
    dry_run: bool = False,
) -> BundleMigrationResult:
    manifest_path = next(
        (
            policy_dir / name
            for name in ("bundle.yaml", "bundle.yml", "bundle.json")
            if (policy_dir / name).exists()
        ),
        None,
    )
    if manifest_path is None:
        raise PolicySchemaError(f"bundle manifest not found in {policy_dir}")

    manifest_payload = _read_mapping(manifest_path)
    if not isinstance(manifest_payload, dict):
        raise PolicySchemaError("bundle manifest must be a mapping")

    source_schema = normalize_schema_version(manifest_payload.get("schema_version"))
    normalized_target = normalize_schema_version(target_schema_version)
    if _is_version_less(normalized_target, source_schema):
        raise PolicySchemaError(
            f"downgrade is not supported (source schema {source_schema}, target schema {normalized_target})"
        )

    changes: list[MigrationChange] = []
    changed_files: set[str] = set()
    warnings: list[str] = []

    current = source_schema
    if current == normalized_target:
        report = MigrationReport(
            source_schema_version=source_schema,
            target_schema_version=normalized_target,
            changed_files=[],
            changes=[],
            warnings=["bundle already uses target schema version"],
        )
        return BundleMigrationResult(report=report, applied=False)

    if current == SCHEMA_VERSION_V1 and normalized_target == SCHEMA_VERSION_V2:
        before_manifest = manifest_path.read_text()
        manifest_payload["schema_version"] = SCHEMA_VERSION_V2
        manifest_payload.setdefault(
            "runtime_compatibility",
            {
                "min_evaluator_version": "0.3.0",
                "max_evaluator_version": "1.0.0",
            },
        )
        after_manifest = _render_payload(manifest_path, manifest_payload)
        if before_manifest != after_manifest:
            rel = str(manifest_path.relative_to(policy_dir))
            changes.append(
                MigrationChange(
                    file=rel,
                    description="bump manifest schema_version and add runtime compatibility defaults",
                    before=before_manifest,
                    after=after_manifest,
                )
            )
            changed_files.add(rel)
            if not dry_run:
                manifest_path.write_text(after_manifest)

        for pattern in ("*.yaml", "*.yml", "*.json"):
            for rule_file in sorted(policy_dir.glob(pattern)):
                if rule_file.name in {
                    "bundle.yaml",
                    "bundle.yml",
                    "bundle.json",
                    "release-manifest.json",
                }:
                    continue
                payload = _read_mapping(rule_file)
                if not isinstance(payload, list):
                    continue
                mutated = False
                for rule in payload:
                    if not isinstance(rule, dict):
                        continue
                    if "action" in rule and "applies_to" not in rule:
                        raw = rule.pop("action")
                        if isinstance(raw, str) and raw:
                            rule["applies_to"] = [raw]
                            mutated = True
                if mutated:
                    before_rules = rule_file.read_text()
                    after_rules = _render_payload(rule_file, payload)
                    rel = str(rule_file.relative_to(policy_dir))
                    changes.append(
                        MigrationChange(
                            file=rel,
                            description="replace deprecated 'action' rule field with 'applies_to'",
                            before=before_rules,
                            after=after_rules,
                        )
                    )
                    changed_files.add(rel)
                    warnings.append(
                        f"{rel}: migrated deprecated rule field 'action' to 'applies_to'"
                    )
                    if not dry_run:
                        rule_file.write_text(after_rules)

    report = MigrationReport(
        source_schema_version=source_schema,
        target_schema_version=normalized_target,
        changed_files=sorted(changed_files),
        changes=changes,
        warnings=warnings,
    )
    return BundleMigrationResult(
        report=report, applied=(not dry_run and bool(changed_files))
    )

def format_migration_report(result: BundleMigrationResult) -> dict[str, object]:
    report = result.report
    return {
        "source_schema_version": report.source_schema_version,
        "target_schema_version": report.target_schema_version,
        "changed_files": report.changed_files,
        "changes": [
            {
                "file": change.file,
                "description": change.description,
                "diff": _diff(change.before, change.after, change.file),
            }
            for change in report.changes
        ],
        "warnings": report.warnings,
        "applied": result.applied,
    }
