#!/usr/bin/env bash
# ClickTask updater: checks the latest GitHub release and installs it over the
# managed install. Nothing is touched during a git checkout — use
# `./tools/install.sh` first.
set -euo pipefail

PREFIX="${CLICKTASK_PREFIX:-${XDG_DATA_HOME:-$HOME/.local/share}/clicktask}"

if [ ! -f "$PREFIX/src/main.py" ]; then
    echo "ClickTask is not installed at $PREFIX; run ./tools/install.sh first." >&2
    exit 1
fi

PY="$PREFIX/.venv/bin/python"
if [ ! -x "$PY" ]; then
    PY="$(command -v python3 || true)"
fi
if [ -z "$PY" ]; then
    echo "ClickTask: python3 not found" >&2
    exit 1
fi

exec "$PY" "$PREFIX/src/main.py" update "$@"
