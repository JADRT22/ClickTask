#!/usr/bin/env bash
# ClickTask uninstaller: removes the local venv, caches and (with --purge) the
# user config. Nothing was ever installed system-wide.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/clicktask"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PURGE=0
case "${1:-}" in
    --purge) PURGE=1 ;;
    -h|--help)
        echo "Usage: $0 [--purge]"
        echo "  --purge   also delete $CONFIG_DIR (your saved settings)"
        exit 0
        ;;
esac

if [ -d "$REPO_DIR/.venv" ]; then
    rm -rf "$REPO_DIR/.venv"
    echo -e "${GREEN}Removed $REPO_DIR/.venv${NC}"
else
    echo -e "${YELLOW}No .venv to remove.${NC}"
fi

find "$REPO_DIR" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
echo -e "${GREEN}Removed Python caches.${NC}"

if [ "$PURGE" = "1" ]; then
    if [ -d "$CONFIG_DIR" ]; then
        rm -rf "$CONFIG_DIR"
        echo -e "${GREEN}Removed $CONFIG_DIR${NC}"
    else
        echo -e "${YELLOW}No config directory at $CONFIG_DIR.${NC}"
    fi
else
    echo -e "${YELLOW}Kept $CONFIG_DIR (use --purge to delete your settings).${NC}"
fi

echo "ClickTask was never installed system-wide: no packages, services or udev rules."
