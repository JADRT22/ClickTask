#!/usr/bin/env bash
# ClickTask installer: checks tkinter, creates .venv and installs python-xlib.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$REPO_DIR/.venv"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}== ClickTask installer ==${NC}"

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
echo -e "${GREEN}tkinter found.${NC}"

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo -e "${GREEN}Created $VENV_DIR${NC}"
fi

"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$REPO_DIR/requirements.txt"
echo -e "${GREEN}python-xlib installed in the venv.${NC}"

if [ -n "${DISPLAY:-}" ]; then
    echo -e "${GREEN}X display detected ($DISPLAY).${NC}"
else
    echo -e "${YELLOW}No DISPLAY set: run ClickTask from your X session (X11/XFCE).${NC}"
fi

echo -e "\nDone. Start the GUI with ${GREEN}./run.sh${NC} or use the CLI, e.g."
echo "  ./run.sh click --interval 100ms --count 50 --at 800,600"
