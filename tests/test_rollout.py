from __future__ import annotations

from sena.services.rollout import load_rollout_config


def test_rollout_resolve_prefers_specific_rule(tmp_path) -> None:
    config_path = tmp_path / "rollout.yaml"
    config_path.write_text(
        """
default_mode: legacy
default_policy_bundle: legacy:stable
rules:
  - business_unit: finance
    mode: parallel
    policy_bundle: sena:2026.03
    parallel_candidate_bundle: sena:2026.04
  - business_unit: finance
    regions: [eu-west-1]
    mode: sena
    policy_bundle: sena:2026.04
""".strip(),
        encoding="utf-8",
    )
    config = load_rollout_config(config_path)

    eu_target = config.resolve(business_unit="finance", region="eu-west-1")
    us_target = config.resolve(business_unit="finance", region="us-east-1")
    unknown_target = config.resolve(business_unit="hr", region="us-east-1")

    assert eu_target.mode == "sena"
    assert us_target.mode == "parallel"
    assert us_target.parallel_candidate_bundle == "sena:2026.04"
    assert unknown_target.mode == "legacy"


def test_rollout_uses_supported_defaults_when_not_provided(tmp_path) -> None:
    config_path = tmp_path / "rollout.yaml"
    config_path.write_text(
        """
rules:
  - business_unit: finance
    mode: parallel
    policy_bundle: sena:2026.03
    parallel_candidate_bundle: sena:2026.04
""".strip(),
        encoding="utf-8",
    )
    config = load_rollout_config(config_path)

    unknown_target = config.resolve(business_unit="hr", region="us-east-1")

    assert unknown_target.mode == "sena"
    assert unknown_target.policy_bundle == "sena:stable"
