#!/usr/bin/env bash
# ClickTask uninstaller: removes the launcher, menu entry, desktop shortcut,
# icon and update timer, then the installed tree. `--purge` also deletes the
# saved settings. User scope only: no sudo, no system directories.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
PREFIX="${CLICKTASK_PREFIX:-${XDG_DATA_HOME:-$HOME/.local/share}/clicktask}"
PURGE=0

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

usage() {
    cat <<EOF
Usage: $0 [options]

  --prefix DIR   installed directory (default: ~/.local/share/clicktask)
  --purge        also delete the saved settings (~/.config/clicktask)
  -h, --help     show this help
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --purge) PURGE=1; shift ;;
        --prefix)
            PREFIX="${2:?--prefix needs a directory}"
            shift 2
            ;;
        --prefix=*) PREFIX="${1#*=}"; shift ;;
        -h|--help) usage; exit 0 ;;
        *)
            echo "unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

case "$PREFIX" in
    "~") PREFIX="$HOME" ;;
    "~/"*) PREFIX="$HOME/${PREFIX#\~/}" ;;
esac

if [ -f "$PREFIX/.clicktask-install" ]; then
    PY="$PREFIX/.venv/bin/python"
    [ -x "$PY" ] || PY="python3"
    ARGS=(uninstall --prefix "$PREFIX")
    [ "$PURGE" = "1" ] && ARGS+=(--purge)
    if ! "$PY" "$PREFIX/src/installer.py" "${ARGS[@]}"; then
        echo -e "${YELLOW}Could not run the Python uninstaller; removing files directly.${NC}"
    fi
    rm -rf "$PREFIX"
    echo -e "${GREEN}Removed $PREFIX${NC}"
else
    echo -e "${YELLOW}$PREFIX is not an installed ClickTask copy: leaving it alone.${NC}"
    if [ "$PREFIX" = "$REPO_DIR" ]; then
        echo "This is the git checkout; delete it yourself if you want."
    fi
fi

if [ "$PURGE" = "1" ]; then
    CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/clicktask"
    rm -rf "$CONFIG_DIR"
    echo -e "${GREEN}Removed $CONFIG_DIR${NC}"
else
    echo "Kept your settings (use --purge to delete them)."
fi

echo -e "${GREEN}ClickTask removed.${NC} Nothing was installed system-wide."
