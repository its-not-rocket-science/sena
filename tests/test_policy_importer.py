from __future__ import annotations

from sena.policy.importer import import_legacy_policy_file
from sena.policy.parser import load_policy_bundle


def test_import_legacy_policies_object_payload(tmp_path) -> None:
    legacy = tmp_path / "legacy.yaml"
    legacy.write_text(
        """
policies:
  - policy_id: legacy_block_large
    name: Block large unverified vendor payments
    action: approve_vendor_payment
    severity: high
    hard_block: true
    when:
      all:
        - field: amount
          gte: 25000
        - field: vendor_verified
          equals: false
    outcome: deny
    justification: High-value transfer without verification
""".strip(),
        encoding="utf-8",
    )
    output = tmp_path / "converted"
    result = import_legacy_policy_file(
        source_path=legacy,
        output_dir=output,
        bundle_name="enterprise-controls",
        bundle_version="2026.04",
        owner="risk",
    )

    rules, metadata = load_policy_bundle(output)

    assert result.source_rule_count == 1
    assert result.output_rule_count == 1
    assert metadata.bundle_name == "enterprise-controls"
    assert metadata.version == "2026.04"
    assert rules[0].id == "legacy_block_large"
    assert rules[0].decision.value == "BLOCK"


def test_import_legacy_list_payload(tmp_path) -> None:
    legacy = tmp_path / "legacy.json"
    legacy.write_text(
        """
[
  {
    "id": "legacy_allow_small",
    "description": "Allow small refunds",
    "applies_to": ["release_refund"],
    "severity": "low",
    "inviolable": false,
    "condition": {"all": [{"field": "amount", "lte": 100}]},
    "decision": "approve",
    "reason": "safe amount"
  }
]
""".strip(),
        encoding="utf-8",
    )

    output = tmp_path / "converted"
    result = import_legacy_policy_file(
        source_path=legacy,
        output_dir=output,
        bundle_name="enterprise-controls",
        bundle_version="2026.04",
    )

    assert "bundle.yaml" in result.output_files
    assert any(name.endswith("_imported.yaml") for name in result.output_files)
