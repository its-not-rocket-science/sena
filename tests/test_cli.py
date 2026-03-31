import json
import os
import subprocess
import sys


def test_cli_json_output_contains_audit_fields() -> None:
    cmd = [
        sys.executable,
        "-m",
        "sena.cli.main",
        "src/sena/examples/scenarios/demo_vendor_payment_block_unverified.json",
        "--json",
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = f"src:{env.get('PYTHONPATH', '')}".rstrip(":")
    result = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
    payload = json.loads(result.stdout)

    assert payload["decision_id"].startswith("dec_")
    assert payload["decision"] == payload["outcome"]
    assert payload["policy_bundle"]["bundle_name"] == "default-bundle"
    assert "precedence_explanation" in payload["reasoning"]
