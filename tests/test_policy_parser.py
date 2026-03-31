import pytest

from sena.policy.parser import parse_policy_file


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
    policy_file = tmp_path / "bundle.json"
    policy_file.write_text(
        '[{"id":"r1","description":"d","severity":"low","inviolable":false,"applies_to":["a"],"condition":{"field":"x","eq":1},"decision":"ALLOW","reason":"ok"}]'
    )

    rules = parse_policy_file(policy_file)
    assert len(rules) == 1
    assert rules[0].id == "r1"
