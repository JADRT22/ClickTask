#!/usr/bin/env bash
# Root wrapper for the ClickTask installer.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/tools/install.sh" "$@"
