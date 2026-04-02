from __future__ import annotations

from pathlib import Path


EXAMPLES_ROOT = Path(__file__).resolve().parent
DEFAULT_POLICY_DIR = EXAMPLES_ROOT / "policies"
DEFAULT_SCENARIO_PATH = (
    EXAMPLES_ROOT / "scenarios" / "demo_vendor_payment_block_unverified.json"
)
