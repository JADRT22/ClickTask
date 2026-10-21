# -*- coding: utf-8 -*-
"""
ClickTask - backend.py
Description: Input backends. X11Backend injects clicks through XTEST
             (python-xlib), which needs no root on a local X server;
             DryRunBackend records what would happen, for tests, CI and
             `--dry-run`.
Author: JADRT22 (https://github.com/JADRT22)
License: MIT
"""

import select
import time

try:  # python-xlib is only needed for real clicking
    from Xlib import X, XK
    from Xlib.display import Display
except ImportError:  # pragma: no cover - exercised only without the dep
    X = None
    XK = None
    Display = None

# X11 button numbers: left=1, middle=2, right=3
BUTTON_CODES = {"left": 1, "middle": 2, "right": 3}

# Gap between the two presses of a double click. X servers use 200 ms as the
# default double-click window; 40 ms keeps the pair inside it while staying
# fast enough to be invisible at high click rates.
DOUBLE_GAP_S = 0.04


class BackendError(RuntimeError):
    """Raised when a backend cannot be created or used."""


class DryRunBackend:
    """Records actions instead of injecting them."""

    def __init__(self):
        self.actions = []

    def click(self, button="left", double=False, hold_ms=0):
        self.actions.append(("click", button, bool(double), int(hold_ms)))

    def move(self, x, y):
        self.actions.append(("move", int(x), int(y)))

    def position(self):
        return (0, 0)

    def close(self):
        pass

    def describe(self):
        """One line per recorded action, for CLI output."""
        lines = []
        for action in self.actions:
            if action[0] == "click":
                _, button, double, hold_ms = action
                kind = "double" if double else "single"
                suffix = f" hold {hold_ms}ms" if hold_ms else ""
                lines.append(f"click {button} ({kind}){suffix}")
            else:
                _, x, y = action
                lines.append(f"move {x},{y}")
        return lines


class X11Backend:
    """XTEST-based clicking on a local X server."""

    def __init__(self, display_name=None):
        if Display is None:
            raise BackendError(
                "python-xlib is not installed (pip install python-xlib)"
            )
        try:
            self._display = Display(display_name) if display_name else Display()
            self._root = self._display.screen().root
        except Exception as exc:
            raise BackendError(f"cannot open the X display: {exc}") from exc

    def click(self, button="left", double=False, hold_ms=0):
        code = BUTTON_CODES.get(button)
        if code is None:
            raise BackendError(f"unsupported button: {button}")
        presses = 2 if double else 1
        for index in range(presses):
            self._send(X.ButtonPress, code)
            if hold_ms:
                time.sleep(hold_ms / 1000.0)
            self._send(X.ButtonRelease, code)
            if double and index == 0:
                time.sleep(DOUBLE_GAP_S)
        return True

    def move(self, x, y):
        self._display.xtest_fake_input(
            X.MotionNotify, root=self._root.id, x=int(x), y=int(y)
        )
        self._display.sync()

    def position(self):
        data = self._root.query_pointer()._data
        return (int(data["root_x"]), int(data["root_y"]))

    def close(self):
        try:
            self._display.close()
        except Exception:
            pass

    def _send(self, event_type, code):
        self._display.xtest_fake_input(event_type, detail=code)
        self._display.sync()


def make_backend(dry_run=False, display_name=None):
    """Build the best backend available for the requested mode."""
    if dry_run:
        return DryRunBackend()
    return X11Backend(display_name)


def capture_click(timeout=60.0, display_name=None):
    """Block until the next pointer click and return its screen position.

    The pointer is grabbed for the duration, so the click is consumed here
    instead of activating whatever is under the cursor. Returns ``None`` when
    the user presses Escape or the timeout expires.
    """
    if Display is None:
        raise BackendError("python-xlib is not installed (pip install python-xlib)")
    try:
        display = Display(display_name) if display_name else Display()
    except Exception as exc:
        raise BackendError(f"cannot open the X display: {exc}") from exc
    try:
        return _wait_for_click(display, timeout)
    finally:
        try:
            display.close()
        except Exception:
            pass


def _wait_for_click(display, timeout=60.0):
    """Inner loop of :func:`capture_click`, split out so tests can drive it."""
    root = display.screen().root
    grab = root.grab_pointer(
        False,
        X.ButtonPressMask,
        X.GrabModeAsync,
        X.GrabModeAsync,
        X.NONE,
        X.NONE,
        X.CurrentTime,
    )
    if grab != X.GrabSuccess:
        raise BackendError("could not grab the pointer; close other utilities and retry")

    escape = 0
    if XK is not None:
        escape = display.keysym_to_keycode(XK.string_to_keysym("Escape")) or 0
    if escape:
        try:  # best effort: Escape cancels, but the click still works without it
            root.grab_key(escape, 0, True, X.GrabModeAsync, X.GrabModeAsync)
        except Exception:
            escape = 0
    display.sync()

    deadline = time.monotonic() + timeout
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            if not select.select([display.fileno()], [], [], remaining)[0]:
                return None
            event = display.next_event()
            if event.type == X.ButtonPress:
                return (int(event.root_x), int(event.root_y))
            if event.type == X.KeyPress:
                return None
    finally:
        try:
            if escape:
                root.ungrab_key(escape, 0)
            display.ungrab_pointer(X.CurrentTime)  # lives on Display, not Window
            display.sync()
        except Exception:
            pass
