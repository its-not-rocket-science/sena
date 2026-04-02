#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

export PYTHONPATH=src

echo "== 1) Run integration pack =="
python examples/design_partner_reference/run_reference.py

echo "== 2) Promotion gate summary =="
python - <<'PY'
import json
from pathlib import Path
root = Path("examples/design_partner_reference/artifacts")
sim = json.loads((root / "simulation-report.json").read_text())
promo = json.loads((root / "promotion-validation.json").read_text())
print({
    "changed_scenarios": sim["changed_scenarios"],
    "promotion_valid": promo["promotion_validation"]["valid"],
    "signature_valid": promo["signature_verification"]["valid"],
})
PY

echo "== 3) Deterministic replay check =="
python - <<'PY'
import json
from pathlib import Path
root = Path("examples/design_partner_reference/artifacts")
stable = json.loads((root / "replay-report-stable.json").read_text())
update = json.loads((root / "replay-report-policy-update.json").read_text())
print({
    "stable_changed_outcomes": stable["changed_outcomes"],
    "update_changed_outcomes": update["changed_outcomes"],
})
PY

echo "== 4) Portability proof (normalized events) =="
python - <<'PY'
import json
from pathlib import Path
rows = json.loads(Path("examples/design_partner_reference/artifacts/normalized-event-examples.json").read_text())
print([{ "source_system": r["source_system"], "decision": r["decision"] } for r in rows])
PY

echo "Demo complete. Inspect examples/design_partner_reference/artifacts for full evidence bundle."
