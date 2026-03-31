from sena.policy.parser import parse_policy_file


def test_policy_parser_loads_yaml() -> None:
    rules = parse_policy_file("src/sena/examples/policies/data_access.yaml")
    assert len(rules) == 2
    assert rules[0].id == "never_export_ssn_without_legal_basis"
