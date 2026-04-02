#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="${ROOT_DIR}/examples/.tmp-policy-registry.db"
SCENARIOS_PATH="${ROOT_DIR}/examples/simulation_scenarios.json"

export PYTHONPATH="${ROOT_DIR}/src:${PYTHONPATH:-}"
export SENA_PROMOTION_GATE_REQUIRE_VALIDATION_ARTIFACT=true
export SENA_PROMOTION_GATE_REQUIRE_SIMULATION=true
export SENA_PROMOTION_GATE_REQUIRED_SCENARIO_IDS="jira-vendor-small,jira-vendor-large-unverified"
export SENA_PROMOTION_GATE_MAX_CHANGED_OUTCOMES=2
export SENA_PROMOTION_GATE_MAX_REGRESSIONS_BY_OUTCOME_TYPE='{"BLOCKED->APPROVED":0}'

rm -f "${DB_PATH}"

echo "== Register candidate bundle =="
python -m sena.cli.main registry --sqlite-path "${DB_PATH}" register \
  --policy-dir "${ROOT_DIR}/src/sena/examples/policies" \
  --bundle-name enterprise-compliance-controls \
  --bundle-version 2026.10 \
  --created-by ops

BUNDLE_ID="$(python -m sena.cli.main registry --sqlite-path "${DB_PATH}" fetch --bundle-name enterprise-compliance-controls --version 2026.10 | python -c 'import json,sys; print(json.load(sys.stdin)["bundle_id"])')"

python -m sena.cli.main registry --sqlite-path "${DB_PATH}" promote \
  --bundle-id "${BUNDLE_ID}" \
  --target-lifecycle candidate \
  --promoted-by ops \
  --promotion-reason "ready for simulation"

echo "== Expected failure: missing simulation evidence =="
set +e
python -m sena.cli.main registry --sqlite-path "${DB_PATH}" promote \
  --bundle-id "${BUNDLE_ID}" \
  --target-lifecycle active \
  --promoted-by ops \
  --promotion-reason "attempt without simulation" \
  --validation-artifact CAB-101
FAIL_CODE=$?
set -e
if [[ ${FAIL_CODE} -eq 0 ]]; then
  echo "Expected active promotion to fail without simulation report" >&2
  exit 1
fi

echo "== Passing promotion with validation + required simulation suite =="
python -m sena.cli.main registry --sqlite-path "${DB_PATH}" promote \
  --bundle-id "${BUNDLE_ID}" \
  --target-lifecycle active \
  --promoted-by ops \
  --promotion-reason "all gates passed" \
  --validation-artifact CAB-102 \
  --simulation-scenarios "${SCENARIOS_PATH}" \
  --max-changed-outcomes 2 \
  --max-regression-budget BLOCKED-\>APPROVED=0

python -m sena.cli.main registry --sqlite-path "${DB_PATH}" fetch-active --bundle-name enterprise-compliance-controls
