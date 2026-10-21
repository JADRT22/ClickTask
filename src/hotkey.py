# -*- coding: utf-8 -*-
"""
ClickTask - hotkey.py
Description: Global start/stop hotkey on X11 through XGrabKey (python-xlib).
             The listener owns its own Display connection, because python-xlib
             objects must not be shared between threads.
Author: JADRT22 (https://github.com/JADRT22)
License: MIT
"""

import threading

try:
    from Xlib import X, XK
    from Xlib.display import Display
except ImportError:  # pragma: no cover - exercised only without the dep
    X = None
    XK = None
    Display = None

# Modifier masks a key can be grabbed with: bare, CapsLock, NumLock, both.
# Without the lock variants the grab silently stops working after CapsLock.
LOCK_VARIANTS = (0, 2, 16, 18)  # 2 = LockMask, 16 = Mod2Mask (NumLock)


class HotkeyError(RuntimeError):
    """Raised when the hotkey cannot be registered."""


def parse_hotkey(name):
    """Turn "F6" / "f6" / "space" into its canonical keysym name.

    Raises HotkeyError for unknown names, so the GUI/CLI can report the
    problem instead of silently failing to grab.
    """
    if not isinstance(name, str) or not name.strip():
        raise HotkeyError("hotkey cannot be empty")
    if XK is None:
        return name.strip()  # without python-xlib we cannot validate
    text = name.strip()
    candidate = text if len(text) > 1 else text.upper()
    upper = candidate.upper()
    for variant in (candidate, upper, candidate.capitalize(), candidate.lower()):
        if XK.string_to_keysym(variant):
            return variant
    raise HotkeyError(f"unknown key: {name}")


def display_for(display_name=None):
    if Display is None:
        raise HotkeyError("python-xlib is not installed")
    try:
        return Display(display_name) if display_name else Display()
    except Exception as exc:
        raise HotkeyError(f"cannot open the X display: {exc}") from exc


class HotkeyListener:
    """Grabs `hotkey` on the root window and calls `callback` on each press.

    Key auto-repeat is filtered: one callback per physical press, released
    when the key goes up.
    """

    def __init__(self, hotkey="F6", callback=None, display_name=None):
        self.hotkey = parse_hotkey(hotkey)
        self._callback = callback or (lambda: None)
        self._display_name = display_name
        self._display = None
        self._keycode = None
        self._thread = None
        self._running = threading.Event()
        self._pressed = False

    @property
    def running(self):
        return self._running.is_set()

    def start(self):
        """Grab the key and start listening. Raises HotkeyError on failure."""
        if self.running:
            return True
        self._display = display_for(self._display_name)
        self._keycode = self._display.keysym_to_keycode(
            XK.string_to_keysym(self.hotkey)
        )
        if not self._keycode:
            raise HotkeyError(f"key {self.hotkey} has no keycode on this layout")
        root = self._display.screen().root
        for extra in LOCK_VARIANTS:
            root.grab_key(self._keycode, extra, True, X.GrabModeAsync, X.GrabModeAsync)
        self._display.sync()
        self._running.set()
        self._thread = threading.Thread(
            target=self._loop, name="clicktask-hotkey", daemon=True
        )
        self._thread.start()
        return True

    def stop(self):
        """Release the grab and stop listening."""
        self._running.clear()
        display = self._display
        if display is None:
            return
        try:
            root = display.screen().root
            for extra in LOCK_VARIANTS:
                root.ungrab_key(self._keycode, extra)
            display.sync()
        except Exception:
            pass
        try:
            display.close()
        except Exception:
            pass
        self._display = None

    def _loop(self):
        display = self._display
        while self._running.is_set():
            try:
                event = display.next_event()
            except Exception:
                return
            if event.type == X.KeyPress:
                if not self._pressed:
                    self._pressed = True
                    self._callback()
            elif event.type == X.KeyRelease:
                self._pressed = False
