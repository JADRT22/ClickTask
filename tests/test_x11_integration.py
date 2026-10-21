# -*- coding: utf-8 -*-
"""
ClickTask - test_x11_integration.py
Description: Real XTEST integration check. Gated behind CLICKTASK_X11_TEST=1
             so a normal test run never moves the pointer. It creates its own
             window, clicks its centre through X11Backend and verifies the
             ButtonPress arrived, then restores the previous pointer position.
             CI runs it inside Xvfb.
Author: JADRT22 (https://github.com/JADRT22)
License: MIT
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import backend  # noqa: E402

DISPLAY = os.environ.get("DISPLAY")
ENABLED = os.environ.get("CLICKTASK_X11_TEST") == "1"


@unittest.skipUnless(
    ENABLED and DISPLAY,
    "set CLICKTASK_X11_TEST=1 with a display to run the XTEST integration test",
)
class X11IntegrationTests(unittest.TestCase):
    def test_xtest_move_and_click_reach_a_real_window(self):
        import tkinter as tk

        root = tk.Tk()
        root.title("ClickTask XTEST self-test")
        root.geometry("240x170+140+140")
        try:
            root.attributes("-topmost", True)  # no window manager under Xvfb
        except tk.TclError:
            pass

        clicks = []
        label = tk.Label(
            root,
            text="ClickTask XTEST self-test",
            width=30,
            height=6,
            bg="#1d2129",
            fg="#e7eaf0",
        )
        label.pack(fill="both", expand=True)
        label.bind("<ButtonPress-1>", lambda event: clicks.append((event.x_root, event.y_root)))
        root.update()
        for _ in range(25):  # let the X server map the window
            root.update()
            time.sleep(0.02)

        x = root.winfo_rootx() + root.winfo_width() // 2
        y = root.winfo_rooty() + root.winfo_height() // 2

        device = backend.X11Backend()
        previous = None
        try:
            previous = device.position()
            device.move(x, y)
            self.assertEqual(device.position(), (x, y), "XTEST did not move the pointer")
            device.click("left")
            deadline = time.time() + 3
            while time.time() < deadline and not clicks:
                root.update()
                time.sleep(0.02)
        finally:
            if previous is not None:
                device.move(*previous)
            device.close()
            root.destroy()

        self.assertTrue(clicks, "the XTEST click did not reach the test window")

    def test_clicking_a_non_left_button_is_rejected(self):
        device = backend.X11Backend()
        try:
            with self.assertRaises(backend.BackendError):
                device.click("thumb")
        finally:
            device.close()


if __name__ == "__main__":
    unittest.main()
