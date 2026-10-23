# -*- coding: utf-8 -*-
"""
ClickTask - config.py
Description: JSON settings stored in $XDG_CONFIG_HOME/clicktask/config.json.
             Loading always returns a complete, validated dict so a corrupt or
             partially written file can never break startup.
Author: JADRT22 (https://github.com/JADRT22)
License: MIT
"""

import json
import os

APP_NAME = "clicktask"

DEFAULTS = {
    "interval_ms": 100,
    "random_offset_ms": 0,  # ± jitter applied to the interval; 0 = exact
    "button": "left",
    "double": False,
    "hold_ms": 0,
    "count": 0,  # 0 = until stopped
    "use_fixed_position": False,
    "position": None,
    "hotkey": "F6",
    "sequence_loops": 0,
    "sequence_count": 0,  # 0 = no click cap in sequence mode
    "points": [],
    "auto_update": True,  # installed builds check GitHub on startup + daily
}

BUTTONS = ("left", "middle", "right")
MAX_INTERVAL_MS = 24 * 60 * 60 * 1000  # one day, same ceiling as GS's h/m/s/ms fields


def config_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, APP_NAME)


def config_path():
    return os.path.join(config_dir(), "config.json")


def _as_int(value, default, minimum=0, maximum=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < minimum:
        return default
    if maximum is not None and number > maximum:
        return maximum
    return number


def _as_position(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        x, y = int(value[0]), int(value[1])
    except (TypeError, ValueError):
        return None
    if x < 0 or y < 0:
        return None
    return [x, y]


def normalize(raw):
    """Return a complete settings dict built from `raw` (which may be junk)."""
    raw = raw if isinstance(raw, dict) else {}
    settings = dict(DEFAULTS)

    settings["interval_ms"] = _as_int(
        raw.get("interval_ms"), DEFAULTS["interval_ms"], 1, MAX_INTERVAL_MS
    )
    settings["random_offset_ms"] = _as_int(
        raw.get("random_offset_ms"), DEFAULTS["random_offset_ms"], 0, 10000
    )
    button = raw.get("button")
    settings["button"] = button if button in BUTTONS else DEFAULTS["button"]
    settings["double"] = bool(raw.get("double", DEFAULTS["double"]))
    settings["hold_ms"] = _as_int(raw.get("hold_ms"), DEFAULTS["hold_ms"], 0, 60000)
    settings["count"] = _as_int(raw.get("count"), DEFAULTS["count"], 0)
    settings["use_fixed_position"] = bool(
        raw.get("use_fixed_position", DEFAULTS["use_fixed_position"])
    )
    settings["position"] = _as_position(raw.get("position"))
    hotkey = raw.get("hotkey")
    settings["hotkey"] = hotkey.strip() if isinstance(hotkey, str) and hotkey.strip() else DEFAULTS["hotkey"]
    settings["sequence_loops"] = _as_int(
        raw.get("sequence_loops"), DEFAULTS["sequence_loops"], 0
    )
    settings["sequence_count"] = _as_int(
        raw.get("sequence_count"), DEFAULTS["sequence_count"], 0
    )
    settings["points"] = [_normalize_point(p) for p in raw.get("points") or [] if isinstance(p, dict)]
    settings["auto_update"] = bool(raw.get("auto_update", DEFAULTS["auto_update"]))
    return settings


def _normalize_point(point):
    return {
        "x": _as_int(point.get("x"), 0, 0),
        "y": _as_int(point.get("y"), 0, 0),
        "delay_ms": _as_int(point.get("delay_ms"), 0, 0, MAX_INTERVAL_MS),
        "button": point.get("button") if point.get("button") in BUTTONS else "",
        "double": bool(point.get("double", False)),
        "hold_ms": _as_int(point.get("hold_ms"), 0, 0, 60000),
    }


def load(path=None):
    """Load settings, falling back to defaults for anything missing/broken."""
    target = path or config_path()
    try:
        with open(target, "r", encoding="utf-8") as handle:
            return normalize(json.load(handle))
    except (OSError, ValueError):
        return normalize({})


def save(settings, path=None):
    """Persist settings atomically. Returns the path written, or None on failure."""
    target = path or config_path()
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp = f"{target}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(normalize(settings), handle, indent=2)
            handle.write("\n")
        os.replace(tmp, target)
        return target
    except OSError:
        return None
