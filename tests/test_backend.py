# -*- coding: utf-8 -*-
"""
ClickTask - test_backend.py
Description: Backend tests. DryRunBackend is exercised for real; X11Backend is
             driven through a mocked python-xlib Display, so no X server and no
             pointer movement are involved.
Author: JADRT22 (https://github.com/JADRT22)
License: MIT
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import backend  # noqa: E402


class DryRunBackendTests(unittest.TestCase):
    def test_records_clicks_and_moves(self):
        device = backend.DryRunBackend()
        device.move(10, 20)
        device.click("right", double=True, hold_ms=5)
        self.assertEqual(
            device.actions,
            [("move", 10, 20), ("click", "right", True, 5)],
        )

    def test_describe_is_human_readable(self):
        device = backend.DryRunBackend()
        device.move(1, 2)
        device.click("left")
        device.click("middle", double=True, hold_ms=10)
        self.assertEqual(
            device.describe(),
            ["move 1,2", "click left (single)", "click middle (double) hold 10ms"],
        )

    def test_make_backend_returns_dry_run_when_asked(self):
        self.assertIsInstance(backend.make_backend(dry_run=True), backend.DryRunBackend)


class CaptureClickTests(unittest.TestCase):
    """Point picking: the next click is grabbed and returned as coordinates."""

    def setUp(self):
        if backend.Display is None:
            self.skipTest("python-xlib not installed")
        self.display = MagicMock()
        self.root = MagicMock()
        self.display.screen.return_value.root = self.root
        self.root.grab_pointer.return_value = backend.X.GrabSuccess
        self.display.keysym_to_keycode.return_value = 9
        self.patcher = patch.object(backend, "Display", return_value=self.display)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def event(self, kind, **kwargs):
        defaults = {"type": kind, "root_x": 0, "root_y": 0}
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_returns_the_click_coordinates(self):
        click = self.event(backend.X.ButtonPress, root_x=640, root_y=480)
        with patch.object(backend.select, "select", return_value=([1], [], [])), \
                patch.object(self.display, "next_event", return_value=click):
            self.assertEqual(backend.capture_click(timeout=1), (640, 480))
        # The grab must be released: ungrab_pointer lives on the Display.
        self.display.ungrab_pointer.assert_called_once()
        self.display.close.assert_called()

    def test_escape_cancels_the_pick(self):
        escape = self.event(backend.X.KeyPress, detail=9)
        with patch.object(backend.select, "select", return_value=([1], [], [])), \
                patch.object(self.display, "next_event", return_value=escape):
            self.assertIsNone(backend.capture_click(timeout=1))

    def test_timeout_returns_none(self):
        self.assertIsNone(backend.capture_click(timeout=0))
        self.display.ungrab_pointer.assert_called_once()

    def test_grab_failure_is_reported(self):
        self.root.grab_pointer.return_value = 1
        with self.assertRaises(backend.BackendError):
            backend.capture_click(timeout=1)


class X11BackendTests(unittest.TestCase):
    def setUp(self):
        if backend.Display is None:
            self.skipTest("python-xlib not installed")
        self.display = MagicMock()
        self.display.screen.return_value.root.id = 42
        self.patcher = patch.object(backend, "Display", return_value=self.display)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_single_click_sends_press_and_release(self):
        device = backend.X11Backend()
        device.click("left")
        sent = [call.args for call in self.display.xtest_fake_input.call_args_list]
        self.assertEqual(
            sent,
            [(backend.X.ButtonPress,), (backend.X.ButtonRelease,)],
        )

    def test_button_codes_match_x11_numbering(self):
        device = backend.X11Backend()
        for name, code in (("left", 1), ("middle", 2), ("right", 3)):
            self.display.xtest_fake_input.reset_mock()
            device.click(name)
            details = [call.kwargs["detail"] for call in self.display.xtest_fake_input.call_args_list]
            self.assertEqual(details, [code, code])

    def test_double_click_sends_two_pairs(self):
        device = backend.X11Backend()
        with patch.object(backend.time, "sleep") as sleep:
            device.click("left", double=True)
        self.assertEqual(self.display.xtest_fake_input.call_count, 4)
        sleep.assert_called_once_with(backend.DOUBLE_GAP_S)

    def test_hold_sleeps_between_press_and_release(self):
        device = backend.X11Backend()
        with patch.object(backend.time, "sleep") as sleep:
            device.click("left", hold_ms=25)
        sleep.assert_called_once_with(0.025)

    def test_move_warps_the_pointer_through_xtest(self):
        device = backend.X11Backend()
        device.move(640, 480)
        self.display.xtest_fake_input.assert_called_once_with(
            backend.X.MotionNotify, root=42, x=640, y=480
        )
        self.display.sync.assert_called()

    def test_position_reads_the_root_pointer(self):
        self.display.screen.return_value.root.query_pointer.return_value._data = {
            "root_x": 123,
            "root_y": 456,
        }
        device = backend.X11Backend()
        self.assertEqual(device.position(), (123, 456))

    def test_unknown_button_is_rejected(self):
        device = backend.X11Backend()
        with self.assertRaises(backend.BackendError):
            device.click("thumb")

    def test_open_failure_becomes_backend_error(self):
        self.patcher.stop()
        with patch.object(backend, "Display", side_effect=RuntimeError("no display")):
            with self.assertRaises(backend.BackendError):
                backend.X11Backend()
        self.patcher.start()


if __name__ == "__main__":
    unittest.main()
