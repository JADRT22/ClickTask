#!/usr/bin/env bash
# ClickTask launcher: uses .venv when present, otherwise the system Python.
# GUI: `./run.sh`   CLI: `./run.sh click --count 10 --interval 100ms`
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

if [ -x "$REPO_DIR/.venv/bin/python" ]; then
    PYTHON="$REPO_DIR/.venv/bin/python"
else
    PYTHON="python3"
fi

exec "$PYTHON" "$REPO_DIR/src/main.py" "$@"
