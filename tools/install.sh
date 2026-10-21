#!/usr/bin/env bash
# ClickTask installer (user scope, no sudo).
#
# Copies ClickTask to $PREFIX (default ~/.local/share/clicktask), creates its
# venv, then installs the desktop integration:
#   - `clicktask` launcher in ~/.local/bin
#   - menu entry in ~/.local/share/applications (found by the search bar)
#   - shortcut on the desktop
#   - app icon and a daily systemd user timer that installs new releases
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
PREFIX="${CLICKTASK_PREFIX:-${XDG_DATA_HOME:-$HOME/.local/share}/clicktask}"
SHORTCUT=1
AUTOUPDATE=1

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

usage() {
    cat <<EOF
Usage: $0 [options]

  --prefix DIR      install into DIR (default: ~/.local/share/clicktask)
  --no-desktop      do not put a shortcut on the desktop
  --no-autoupdate   do not create the daily update timer
  -h, --help        show this help
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix)
            PREFIX="${2:?--prefix needs a directory}"
            shift 2
            ;;
        --prefix=*)
            PREFIX="${1#*=}"
            shift
            ;;
        --no-desktop) SHORTCUT=0; shift ;;
        --no-autoupdate) AUTOUPDATE=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *)
            echo -e "${RED}unknown option: $1${NC}" >&2
            usage >&2
            exit 2
            ;;
    esac
done

case "$PREFIX" in
    "~") PREFIX="$HOME" ;;
    "~/"*) PREFIX="$HOME/${PREFIX#\~/}" ;;
esac
PREFIX_PARENT="$(dirname "$PREFIX")"
mkdir -p "$PREFIX_PARENT"
PREFIX="$(cd "$PREFIX_PARENT" && pwd)/$(basename "$PREFIX")"

echo -e "${YELLOW}== ClickTask installer ==${NC}"
echo "  from : $REPO_DIR"
echo "  to   : $PREFIX"

if ! command -v python3 >/dev/null 2>&1; then
    echo -e "${RED}python3 not found. Install Python 3.10+ first.${NC}"
    exit 1
fi
python3 -V

if ! python3 -c 'import tkinter' >/dev/null 2>&1; then
    echo -e "${RED}tkinter is missing (needed by the GUI).${NC}"
    echo "  CachyOS/Arch : sudo pacman -S tk"
    echo "  Debian/Ubuntu: sudo apt install python3-tk"
    exit 1
fi

if [ "$REPO_DIR" != "$PREFIX" ]; then
    echo -e "${YELLOW}Copying files…${NC}"
    mkdir -p "$PREFIX"
    tar -C "$REPO_DIR" -cf - \
        --exclude=.venv --exclude=venv --exclude=.git \
        --exclude=__pycache__ --exclude='*.pyc' --exclude=tests \
        --exclude='.clicktask-install' --exclude='.update.lock' \
        src assets docs tools README.md CHANGELOG.md LICENSE requirements.txt run.sh \
        | tar -C "$PREFIX" -xf -
fi

VENV="$PREFIX/.venv"
if [ ! -x "$VENV/bin/python" ]; then
    echo -e "${YELLOW}Creating $VENV…${NC}"
    python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$PREFIX/requirements.txt"
echo -e "${GREEN}python-xlib installed.${NC}"

ARGS=(install --prefix "$PREFIX")
[ "$SHORTCUT" = "0" ] && ARGS+=(--no-desktop)
[ "$AUTOUPDATE" = "0" ] && ARGS+=(--no-autoupdate)
"$VENV/bin/python" "$PREFIX/src/installer.py" "${ARGS[@]}"

if [ -n "${DISPLAY:-}" ]; then
    echo -e "${GREEN}X display detected ($DISPLAY).${NC}"
else
    echo -e "${YELLOW}No DISPLAY set: run ClickTask from your X session (X11/XFCE).${NC}"
fi

case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *)
        echo -e "${YELLOW}Note: ~/.local/bin is not in PATH.${NC}"
        echo "  Add it to open ClickTask from a terminal: export PATH=\"\$HOME/.local/bin:\$PATH\""
        ;;
esac

echo
echo -e "${GREEN}Done.${NC} Open it from the application menu, the desktop shortcut,"
echo -e "or run: ${GREEN}clicktask${NC}  (updates: ${GREEN}clicktask update --check${NC})"
