import pytest

from sena.policy.parser import PolicyParseError, load_policy_bundle, parse_policy_file



def test_policy_parser_loads_yaml() -> None:
    rules = parse_policy_file("src/sena/examples/policies/data_access.yaml")
    assert len(rules) == 2
    assert rules[0].id == "export_block_ssn_without_consent"



def test_policy_parser_rejects_non_list_payload(tmp_path) -> None:
    bad_file = tmp_path / "bad.yaml"
    bad_file.write_text('{"id": "not-a-list"}')

    with pytest.raises(ValueError, match="must contain a list"):
        parse_policy_file(bad_file)



def test_policy_parser_loads_json_policy_file(tmp_path) -> None:
    policy_file = tmp_path / "rules.json"
    policy_file.write_text(
        '[{"id":"r1","description":"d","severity":"low","inviolable":false,"applies_to":["a"],"condition":{"field":"x","eq":1},"decision":"ALLOW","reason":"ok"}]'
    )

    rules = parse_policy_file(policy_file)
    assert len(rules) == 1
    assert rules[0].id == "r1"



def test_load_policy_bundle_includes_integrity_metadata() -> None:
    _, metadata = load_policy_bundle("src/sena/examples/policies")
    assert metadata.integrity_sha256
    assert metadata.policy_file_count >= 1



def test_load_policy_bundle_rejects_missing_directory(tmp_path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(PolicyParseError, match="does not exist"):
        load_policy_bundle(missing)



def test_load_policy_bundle_rejects_invalid_manifest(tmp_path) -> None:
    (tmp_path / "bundle.yaml").write_text("unknown_field: nope")
    (tmp_path / "rules.yaml").write_text(
        '[{"id":"r1","description":"d","severity":"low","inviolable":false,"applies_to":["a"],"condition":{"field":"x","eq":1},"decision":"ALLOW","reason":"ok"}]'
    )

    with pytest.raises(PolicyParseError, match="invalid bundle manifest"):
        load_policy_bundle(tmp_path)


def test_parse_policy_file_supports_deprecated_action_field(tmp_path) -> None:
    policy_file = tmp_path / "legacy_rules.yaml"
    policy_file.write_text(
        """
- id: legacy_rule
  description: old
  severity: low
  inviolable: false
  action: approve_vendor_payment
  condition:
    field: amount
    gt: 5
  decision: ALLOW
  reason: ok
""".strip()
        + "\n"
    )

    rules = parse_policy_file(policy_file)
    assert rules[0].applies_to == ["approve_vendor_payment"]
