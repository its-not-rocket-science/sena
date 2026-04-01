from pathlib import Path

import pytest

from sena.engine.evaluator import PolicyEvaluator
from sena.policy.parser import PolicyParseError, load_policy_bundle
from sena.policy.schema_evolution import (
    CURRENT_BUNDLE_SCHEMA_VERSION,
    evaluate_bundle_compatibility,
    format_migration_report,
    migrate_bundle,
)


FIXTURE_DIR = Path("tests/fixtures/migrations/legacy_bundle_v1")


def test_migrate_bundle_dry_run_reports_changes(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "bundle.yaml").write_text((FIXTURE_DIR / "bundle.yaml").read_text())
    (bundle / "policy.yaml").write_text(
        """
- id: allow_small_legacy
  description: allow low-risk
  severity: low
  inviolable: false
  action: approve_vendor_payment
  condition:
    field: amount
    lt: 500
  decision: ALLOW
  reason: legacy rule
""".strip()
        + "\n"
    )

    result = migrate_bundle(bundle, dry_run=True)
    payload = format_migration_report(result)

    assert payload["changed_files"] == ["bundle.yaml", "policy.yaml"]
    assert any("schema_version" in item["diff"] for item in payload["changes"])
    assert any("action" in item["diff"] for item in payload["changes"])


def test_migrate_bundle_applies_changes(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "bundle.yaml").write_text((FIXTURE_DIR / "bundle.yaml").read_text())
    (bundle / "policy.yaml").write_text((FIXTURE_DIR / "policy.yaml").read_text())

    result = migrate_bundle(bundle)
    assert result.applied

    _, metadata = load_policy_bundle(bundle)
    assert metadata.schema_version == CURRENT_BUNDLE_SCHEMA_VERSION


def test_load_policy_bundle_rejects_newer_schema(tmp_path: Path) -> None:
    (tmp_path / "bundle.yaml").write_text(
        "bundle_name: demo\nversion: 1\nschema_version: '99'\n"
    )
    (tmp_path / "rules.yaml").write_text(
        '[{"id":"r1","description":"d","severity":"low","inviolable":false,'
        '"applies_to":["a"],"condition":{"field":"x","eq":1},"decision":"ALLOW","reason":"ok"}]'
    )

    with pytest.raises(PolicyParseError, match="unsupported bundle schema version"):
        load_policy_bundle(tmp_path)


def test_compatibility_warnings_include_schema_v1_deprecation() -> None:
    report = evaluate_bundle_compatibility(schema_version="1", runtime_version="0.3.0")
    assert report.compatible
    assert report.warnings


def test_evaluator_rejects_incompatible_schema() -> None:
    _, metadata = load_policy_bundle("src/sena/examples/policies")
    metadata.schema_version = "99"
    with pytest.raises(ValueError, match="unsupported bundle schema version"):
        PolicyEvaluator([], policy_bundle=metadata)
