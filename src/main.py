# -*- coding: utf-8 -*-
"""
ClickTask - main.py
Description: Entry point. No arguments opens the GUI; any argument is routed to
             the headless CLI (so `clicktask click ...` and
             `clicktask seq points.json` work from scripts and keybinds).
Author: JADRT22 (https://github.com/JADRT22)
License: MIT
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cli  # noqa: E402


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        return cli.main(argv)
    import gui  # imported lazily: the CLI must work without tkinter

    return gui.main()


if __name__ == "__main__":
    sys.exit(main())
