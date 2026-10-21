#!/usr/bin/env bash
# Root wrapper for ClickTask
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/tools/run.sh" "$@"
