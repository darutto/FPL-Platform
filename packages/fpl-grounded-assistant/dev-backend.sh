#!/usr/bin/env bash
# dev-backend.sh — start the FPL Grounded Assistant server for local development.
#
# Usage:
#   cd packages/fpl-grounded-assistant
#   bash dev-backend.sh
#
# What this does:
#   1. Loads API keys from .env (if present).
#   2. The server handles its own sys.path setup at startup (see fpl_server.py
#      lines 53-68), so no manual PYTHONPATH export is required.
#   3. Starts Uvicorn on localhost:8000 with --reload for development.
#
# Prerequisites:
#   - Python venv activated: source ../../.venv/Scripts/activate  (Windows)
#     or: source ../../.venv/bin/activate  (Mac/Linux)
#   - pip install fastapi uvicorn
#   - Copy .env.template to .env and fill in your API keys.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Resolve Python — walk up to find the repo .venv, handling both Unix and
# Windows (Git Bash) path styles.
_find_python() {
  local dir="$SCRIPT_DIR"
  for _ in 1 2 3 4; do
    dir="$(cd "$dir/.." && pwd)"
    if [ -f "$dir/.venv/Scripts/python" ]; then
      echo "$dir/.venv/Scripts/python"; return
    fi
    if [ -f "$dir/.venv/bin/python" ]; then
      echo "$dir/.venv/bin/python"; return
    fi
  done
  echo "python"
}
PYTHON="$(_find_python)"

# Load .env if present (key=value pairs, ignores comments and blank lines).
if [ -f .env ]; then
  echo "Loading environment from .env..."
  set -o allexport
  # shellcheck disable=SC1091
  source <(grep -v '^\s*#' .env | grep -v '^\s*$')
  set +o allexport
fi

echo "Provider: ${DEFAULT_PROVIDER:-gemini (default)}"
echo "Python:   $PYTHON"
echo "Starting FPL backend on http://localhost:8000 ..."

"$PYTHON" -m uvicorn fpl_server:app --host 127.0.0.1 --port 8000 --reload
