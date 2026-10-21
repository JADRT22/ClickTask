# -*- coding: utf-8 -*-
"""
ClickTask - test_gui.py
Description: GUI tests against a hidden window. Skipped when there is no X
             display (CI). The hotkey grab is patched out so the suite never
             touches a real session, and runs use DryRunBackend, so nothing is
             clicked.
Author: JADRT22 (https://github.com/JADRT22)
License: MIT
"""

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import backend  # noqa: E402
import config  # noqa: E402
import engine  # noqa: E402
import gui  # noqa: E402
import hotkey  # noqa: E402

DISPLAY = os.environ.get("DISPLAY")


@unittest.skipUnless(DISPLAY, "no X display")
class GuiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.environment = patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp})
        self.environment.start()
        self.addCleanup(self.environment.stop)

        self.root = gui.tk.Tk()
        self.root.withdraw()
        self.addCleanup(self._destroy_root)
        with patch.object(hotkey.HotkeyListener, "start", return_value=True):
            self.app = gui.ClickTaskApp(self.root, config.normalize({}))
        self.app.engine = engine.ClickEngine(backend.DryRunBackend())

    def _destroy_root(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_two_tabs_and_default_interval(self):
        self.assertEqual(len(self.app.notebook.tabs()), 2)
        self.assertEqual(self.app.interval_ms(), 100)

    def test_dark_theme_covers_panels_not_only_buttons(self):
        style = gui.ttk.Style(self.root)
        expected = {
            "TFrame": "background",
            "TLabel": "background",
            "TLabelframe": "background",
            "TNotebook": "background",
            "TNotebook.Tab": "background",
            "Treeview": "fieldbackground",
            "Treeview.Heading": "background",
            "TEntry": "fieldbackground",
            "TSpinbox": "fieldbackground",
            "TRadiobutton": "background",
            "TCheckbutton": "background",
        }
        for widget, option in expected.items():
            with self.subTest(style=widget):
                value = style.lookup(widget, option)
                self.assertIn(value, (gui.BG, gui.BG_SOFT, gui.FIELD, gui.FIELD_SOFT),
                              f"{widget}.{option} is {value!r}, not a dark colour")

    def test_interval_fields_combine(self):
        self.app.var_minutes.set("1")
        self.app.var_seconds.set("2")
        self.app.var_millis.set("250")
        self.assertEqual(self.app.interval_ms(), 62250)

    def test_plan_reflects_widgets(self):
        self.app.var_unlimited.set(False)
        self.app.var_count.set("7")
        self.app.var_fixed.set(True)
        self.app.var_x.set("640")
        self.app.var_y.set("480")
        plan = self.app.build_plan()
        self.assertEqual(plan.count, 7)
        self.assertEqual(plan.position, (640, 480))

    def test_sequence_plan_uses_points(self):
        self.app.points = [engine.Point(x=1, y=2, delay_ms=10)]
        self.app.notebook.select(1)
        plan = self.app.build_plan()
        self.assertEqual(plan.mode, engine.SEQUENCE_MODE)

    def test_empty_sequence_is_rejected(self):
        self.app.notebook.select(1)
        with self.assertRaises(ValueError):
            self.app.build_plan()

    def _wait_for_pick(self, timeout=5):
        deadline = time.time() + timeout
        while self.app._pick_active and time.time() < deadline:
            self.root.update()
            time.sleep(0.02)
        self.root.update()
        self.assertFalse(self.app._pick_active, "pick flow did not finish")

    def test_pick_position_stores_the_clicked_point(self):
        with patch.object(gui.backend, "capture_click", return_value=(321, 654)):
            self.app._start_pick("position")
            self._wait_for_pick()
        self.assertEqual(self.app.var_x.get(), "321")
        self.assertEqual(self.app.var_y.get(), "654")
        self.assertTrue(self.app.var_fixed.get())
        self.assertEqual(self.app.position(), (321, 654))
        self.assertIn("321,654", self.app.var_status.get())

    def test_pick_sequence_adds_a_point(self):
        with patch.object(gui.backend, "capture_click", return_value=(10, 20)):
            self.app._start_pick("sequence")
            self._wait_for_pick()
        self.assertEqual(len(self.app.points), 1)
        self.assertEqual((self.app.points[0].x, self.app.points[0].y), (10, 20))
        self.assertEqual(len(self.app.tree.get_children()), 1)

    def test_cancelled_pick_keeps_the_old_position(self):
        self.app.var_fixed.set(True)
        self.app.var_x.set("7")
        self.app.var_y.set("8")
        with patch.object(gui.backend, "capture_click", return_value=None):
            self.app._start_pick("position")
            self._wait_for_pick()
        self.assertEqual(self.app.position(), (7, 8))
        self.assertEqual(self.app.var_status.get(), "Pick cancelled")

    def test_pick_failure_is_reported(self):
        error = gui.backend.BackendError("could not grab the pointer")
        with patch.object(gui.backend, "capture_click", side_effect=error), \
                patch.object(gui.messagebox, "showerror") as showerror:
            self.app._start_pick("position")
            self._wait_for_pick()
        showerror.assert_called_once()
        self.assertEqual(self.app.var_status.get(), "Pick failed")

    def test_manual_update_check_reports_up_to_date(self):
        release = {"version": "1.1.0", "tag": "v1.1.0", "tarball_url": "https://x"}
        with patch("updater.fetch_latest_release", return_value=release), \
                patch("updater.installed_version", return_value="1.1.0"), \
                patch.object(gui.messagebox, "showinfo") as showinfo:
            self.app.check_updates(manual=True)
            deadline = time.time() + 5
            while self.app._update_running and time.time() < deadline:
                self.root.update()
                time.sleep(0.02)
        self.assertFalse(self.app._update_running)
        self.assertIn("up to date", self.app.var_update.get())
        showinfo.assert_called_once()

    def test_run_updates_counter_and_saves_on_close(self):
        self.app.var_unlimited.set(False)
        self.app.var_count.set("3")
        self.app.var_millis.set("5")
        self.app.start()
        deadline = time.time() + 5
        while self.app.engine.running and time.time() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.root.update()
        self.app.stop()
        self.assertEqual(self.app.engine.clicks_done, 3)
        self.assertEqual(self.app.var_counter.get(), "3 clicks")
        self.app.on_close()
        saved = config.load(os.path.join(self.tmp, "clicktask", "config.json"))
        self.assertEqual(saved["count"], 3)


if __name__ == "__main__":
    unittest.main()
