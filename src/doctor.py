# -*- coding: utf-8 -*-
"""
ClickTask - doctor.py
Description: `clicktask doctor` diagnostics: Python, tkinter, python-xlib, the X
             display, the configured hotkey, desktop integration, the update
             timer and the last cached release check. Read-only and safe to run
             while the GUI is open.
Author: JADRT22 (https://github.com/JADRT22)
License: MIT
"""

import argparse
import os
import shutil
import subprocess
import sys
import time

import config
import hotkey
import installer
import updater
from version import VERSION

OK = "ok"
WARN = "warn"
FAIL = "fail"


def entry(level, name, detail=""):
    return {"level": level, "name": name, "detail": detail}


def human_age(seconds):
    if seconds < 60:
        return "less than a minute"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} min"
    hours = int(minutes // 60)
    if hours < 24:
        return f"{hours} h"
    return f"{hours // 24} d"


# --- checks --------------------------------------------------------------


def check_python():
    version = sys.version_info
    ok = version >= (3, 10)
    detail = f"{version.major}.{version.minor}.{version.micro}"
    if not ok:
        detail += " (needs 3.10+)"
    return entry(OK if ok else FAIL, "python", detail)


def check_tkinter():
    try:
        import tkinter

        return entry(OK, "tkinter", f"Tk {tkinter.TkVersion}")
    except Exception as exc:  # missing package or broken install
        return entry(FAIL, "tkinter", str(exc))


def check_xlib():
    try:
        import Xlib
    except Exception as exc:
        return entry(FAIL, "python-xlib", str(exc))
    version = getattr(Xlib, "__version__", None)
    if not version:
        try:
            from importlib.metadata import version as dist_version

            version = dist_version("python-xlib")
        except Exception:
            version = "installed"
    if isinstance(version, (tuple, list)):
        version = ".".join(str(part) for part in version)
    return entry(OK, "python-xlib", str(version))


def check_display(display_name=None):
    name = display_name or os.environ.get("DISPLAY")
    if not name:
        return entry(FAIL, "DISPLAY", "not set (run inside your X session)")
    try:
        from Xlib.display import Display

        display = Display(name)
        screen = display.screen()
        detail = f"{name} · {screen.width_in_pixels}x{screen.height_in_pixels}"
        display.close()
        return entry(OK, "DISPLAY", detail)
    except Exception as exc:
        return entry(FAIL, "DISPLAY", f"{name}: {exc}")


def check_hotkey(display_name=None):
    name = config.load()["hotkey"]
    try:
        canonical = hotkey.parse_hotkey(name)
    except Exception as exc:
        return entry(FAIL, "hotkey", f"{name}: {exc}")
    detail = canonical
    try:
        from Xlib import XK
        from Xlib.display import Display

        display = Display(display_name or os.environ.get("DISPLAY"))
        code = display.keysym_to_keycode(XK.string_to_keysym(canonical))
        display.close()
        if not code:
            return entry(WARN, "hotkey", f"{canonical} has no keycode on this layout")
        detail = f"{canonical} · keycode {code}"
    except Exception:
        pass  # no display: check_display already reports it
    return entry(OK, "hotkey", detail)


def check_install(prefix=None):
    prefix = os.path.abspath(prefix or installer.module_root())
    marker = installer.read_marker(prefix)
    if not marker:
        return entry(WARN, "install", f"{prefix} is not a managed install (git checkout?)")
    missing = [
        os.path.basename(path)
        for path in (installer.launcher_path(), installer.desktop_entry_path())
        if not os.path.exists(path)
    ]
    detail = f"{prefix} · v{marker.get('version', '?')}"
    if missing:
        return entry(WARN, "install", detail + " · missing " + ", ".join(missing))
    return entry(OK, "install", detail)


def check_desktop_shortcut():
    path = installer.desktop_shortcut_path()
    if os.path.exists(path):
        return entry(OK, "desktop shortcut", path)
    return entry(WARN, "desktop shortcut", f"{path} (not created; --no-desktop?)")


def check_timer():
    unit = os.path.join(installer.systemd_dir(), f"{installer.TIMER_NAME}.timer")
    if not os.path.exists(unit):
        return entry(WARN, "update timer", "not installed (--no-autoupdate?)")
    name = f"{installer.TIMER_NAME}.timer"
    if os.environ.get("CLICKTASK_SKIP_SYSTEMCTL") or not shutil.which("systemctl"):
        return entry(OK, "update timer", f"{name} (systemctl unavailable)")
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-enabled", name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        state = (result.stdout or result.stderr).strip() or f"exit {result.returncode}"
        level = OK if result.returncode == 0 else WARN
        return entry(level, "update timer", f"{name} · {state}")
    except (OSError, subprocess.SubprocessError) as exc:
        return entry(WARN, "update timer", f"{name}: {exc}")


def check_update_cache():
    cached = updater.read_cache(max_age=None)
    if not cached:
        return entry(WARN, "update cache", "no check yet; the next launch will do one")
    try:
        age = max(0.0, time.time() - float(cached.get("checked_at", 0)))
    except (TypeError, ValueError):
        age = 0.0
    return entry(OK, "update cache", f"v{cached['version']} · {human_age(age)} ago")


def check_config():
    path = config.config_path()
    try:
        config.load()  # never raises; returns defaults for junk or missing files
    except Exception as exc:  # pragma: no cover - defensive
        return entry(FAIL, "settings", str(exc))
    detail = path if os.path.exists(path) else f"{path} (defaults; not saved yet)"
    return entry(OK, "settings", detail)


def run_checks(prefix=None, display_name=None):
    return [
        check_python(),
        check_tkinter(),
        check_xlib(),
        check_display(display_name),
        check_hotkey(display_name),
        check_install(prefix),
        check_desktop_shortcut(),
        check_timer(),
        check_update_cache(),
        check_config(),
    ]


# --- output --------------------------------------------------------------


def report(entries, out=None):
    """Print the checks and return 1 when a required one failed."""
    out = out or sys.stdout
    for item in entries:
        line = f"  [{item['level']}] {item['name']}"
        if item["detail"]:
            line += f" — {item['detail']}"
        print(line, file=out)
    failures = [item for item in entries if item["level"] == FAIL]
    warnings = [item for item in entries if item["level"] == WARN]
    print("", file=out)
    if failures:
        print(f"{len(failures)} check(s) failed — fix those before clicking.", file=out)
        return 1
    if warnings:
        print(f"{len(warnings)} warning(s); ClickTask should still run.", file=out)
    else:
        print("All checks passed.", file=out)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="clicktask doctor", description="Diagnose a ClickTask installation."
    )
    parser.add_argument("--prefix", default=None, help="install directory to inspect")
    args = parser.parse_args(argv)
    print(f"ClickTask {VERSION} doctor")
    return report(run_checks(args.prefix))


if __name__ == "__main__":
    sys.exit(main())
