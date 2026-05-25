#!/usr/bin/env bash
# capture.sh — run the fpl-historical capture CLI with PYTHONPATH wired.
#
# Usage (from anywhere):
#   bash packages/fpl-historical/capture.sh capture --season 2025-2026
#   bash packages/fpl-historical/capture.sh capture --skip-if-fresh 24
#   bash packages/fpl-historical/capture.sh capture-gw --current
#   bash packages/fpl-historical/capture.sh capture-gw --gw 36 --force
#   bash packages/fpl-historical/capture.sh capture-gw --auto
#
# The subcommand (capture / capture-gw) is passed through from args.
# See packages/fpl-historical/CONTRACT.md §4 and §9.5 for the full flag tables.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Pick venv python if present, else system python.
if [[ -x "$REPO_ROOT/.venv/Scripts/python.exe" ]]; then
  PY="$REPO_ROOT/.venv/Scripts/python.exe"
elif [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PY="$REPO_ROOT/.venv/bin/python"
else
  PY="python"
fi

# Use OS-appropriate PYTHONPATH separator.
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
  SEP=";"
else
  SEP=":"
fi

export PYTHONPATH="$REPO_ROOT/packages/fpl-historical${SEP}$REPO_ROOT/packages/fpl-api-client${PYTHONPATH:+${SEP}${PYTHONPATH}}"

exec "$PY" -m fpl_historical.cli "$@"
