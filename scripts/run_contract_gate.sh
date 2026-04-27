#!/usr/bin/env bash
# run_contract_gate.sh
# =====================
# Local convenience wrapper for the contract drift gate.
# Runs the same runners as the CI job in the same order.
#
# Usage (from repo root, venv activated):
#   bash scripts/run_contract_gate.sh
#
# No API key required. All runners disable orchestration and mock LLM calls.
# See packages/fpl-grounded-assistant/CONTRACT_GATE.md for full details.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PKG_DIR="$REPO_ROOT/packages/fpl-grounded-assistant"

# Resolve Python — walk up to find the repo .venv, handling both Unix and
# Windows (Git Bash) path styles.
_find_python() {
  local dir="$REPO_ROOT"
  if [ -f "$dir/.venv/Scripts/python" ]; then
    echo "$dir/.venv/Scripts/python"; return
  fi
  if [ -f "$dir/.venv/bin/python" ]; then
    echo "$dir/.venv/bin/python"; return
  fi
  echo "python"
}
PYTHON="$(_find_python)"

echo "Contract Drift Gate"
echo "==================="
echo "Python:  $PYTHON"
echo "Package: $PKG_DIR"
echo ""

cd "$PKG_DIR"

PASS=0
FAIL=0

run_runner() {
  local name="$1"
  local file="$2"
  echo "--- $name ---"
  if "$PYTHON" "$file"; then
    PASS=$((PASS + 1))
  else
    FAIL=$((FAIL + 1))
    echo "  FAILED: $file"
  fi
  echo ""
}

run_runner "Orch-4i: gate scope parity checker"       "run_phase_orch4i_tests.py"
run_runner "Orch-4f: contract/fixture drift checker" "run_phase_orch4f_tests.py"
run_runner "Orch-4e: orch_outcome contract parity"   "run_phase_orch4e_tests.py"
run_runner "Orch-4d: squad_context override parity"  "run_phase_orch4d_tests.py"
run_runner "Orch-4c: orchestration audit parity"     "run_phase_orch4c_tests.py"
run_runner "Orch-4a: orch enable/disable flag parity" "run_phase_orch4a_tests.py"
run_runner "Orch-4b: orch_outcome serialization"      "run_phase_orch4b_tests.py"

echo "==================="
echo "Contract gate: $PASS passed, $FAIL failed"
echo "==================="

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
