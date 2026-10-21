# -*- coding: utf-8 -*-
"""
ClickTask - test_hotkey.py
Description: Hotkey tests: name parsing, the lock-modifier variants, grab/
             ungrab calls against a fake display, and that key auto-repeat
             fires the callback once per physical press.
Author: JADRT22 (https://github.com/JADRT22)
License: MIT
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import hotkey  # noqa: E402


class ParseHotkeyTests(unittest.TestCase):
    def test_common_names(self):
        self.assertEqual(hotkey.parse_hotkey("f6"), "F6")
        self.assertEqual(hotkey.parse_hotkey(" F6 "), "F6")
        self.assertEqual(hotkey.parse_hotkey("space"), "space")

    def test_empty_is_rejected(self):
        for value in ("", "   ", None):
            with self.subTest(value=value):
                with self.assertRaises(hotkey.HotkeyError):
                    hotkey.parse_hotkey(value)

    @unittest.skipIf(hotkey.XK is None, "python-xlib not installed")
    def test_unknown_key_is_rejected(self):
        with self.assertRaises(hotkey.HotkeyError):
            hotkey.parse_hotkey("definitely-not-a-key")


class FakeDisplay:
    """Minimal stand-in for an Xlib display."""

    def __init__(self, events=None):
        self.events = list(events or [])
        self.root = MagicMock()
        self.grabbed = []
        self.ungrabbed = []
        self.root.grab_key.side_effect = lambda code, mods, *a: self.grabbed.append((code, mods))
        self.root.ungrab_key.side_effect = lambda code, mods: self.ungrabbed.append((code, mods))
        self.screen = lambda: SimpleNamespace(root=self.root)
        self.closed = False

    def keysym_to_keycode(self, keysym):
        return 96

    def sync(self):
        pass

    def close(self):
        self.closed = True

    def next_event(self):
        if not self.events:
            raise RuntimeError("no more events")
        return self.events.pop(0)


class ListenerTests(unittest.TestCase):
    def test_grab_and_ungrab_cover_lock_variants(self):
        display = FakeDisplay()
        with patch.object(hotkey, "display_for", return_value=display):
            listener = hotkey.HotkeyListener("F6", callback=lambda: None)
            listener.start()
            self.assertTrue(listener.running)
            listener.stop()
        self.assertEqual([mods for _code, mods in display.grabbed], list(hotkey.LOCK_VARIANTS))
        self.assertEqual([mods for _code, mods in display.ungrabbed], list(hotkey.LOCK_VARIANTS))
        self.assertTrue(display.closed)
        self.assertFalse(listener.running)

    def test_missing_keycode_is_reported(self):
        display = FakeDisplay()
        display.keysym_to_keycode = lambda keysym: 0
        with patch.object(hotkey, "display_for", return_value=display):
            listener = hotkey.HotkeyListener("F6")
            with self.assertRaises(hotkey.HotkeyError):
                listener.start()

    def test_display_failure_is_reported(self):
        with patch.object(hotkey, "display_for", side_effect=hotkey.HotkeyError("boom")):
            with self.assertRaises(hotkey.HotkeyError):
                hotkey.HotkeyListener("F6").start()

    def test_auto_repeat_fires_once_per_press(self):
        key_press = SimpleNamespace(type=hotkey.X.KeyPress if hotkey.X else 2)
        key_release = SimpleNamespace(type=hotkey.X.KeyRelease if hotkey.X else 3)
        display = FakeDisplay([key_press, key_press, key_release, key_press])
        calls = []
        listener = hotkey.HotkeyListener("F6", callback=lambda: calls.append(1))
        listener._display = display
        listener._running.set()
        listener._loop()
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
