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

import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import backend  # noqa: E402
import config  # noqa: E402
import engine  # noqa: E402
import gui  # noqa: E402
import hotkey  # noqa: E402

DISPLAY = os.environ.get("DISPLAY")
REQUIRE_DISPLAY = os.environ.get("CLICKTASK_REQUIRE_DISPLAY") == "1"


@unittest.skipUnless(REQUIRE_DISPLAY, "only when a display is required")
class DisplayRequiredTests(unittest.TestCase):
    def test_display_is_available(self):
        self.assertTrue(DISPLAY, "CLICKTASK_REQUIRE_DISPLAY=1 but DISPLAY is unset")


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
            "TCombobox": "fieldbackground",
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

    def test_sequence_plan_carries_click_cap_and_hold(self):
        self.app.points = [engine.Point(x=1, y=2, delay_ms=10)]
        self.app.notebook.select(1)
        self.app.var_seq_count.set("5")
        self.app.var_hold.set("30")
        plan = self.app.build_plan()
        self.assertEqual(plan.count, 5)
        self.assertEqual(plan.hold_ms, 30)

    def test_sequence_table_shows_per_point_hold(self):
        self.app.points = [engine.Point(x=1, y=2, delay_ms=10, hold_ms=40)]
        self.app._refresh_points()
        values = self.app.tree.item(self.app.tree.get_children()[0], "values")
        self.assertEqual(int(values[5]), 40)

    def test_save_point_updates_delay_button_and_hold(self):
        self.app.points = [engine.Point(x=1, y=2)]
        self.app._refresh_points()
        saved = self.app._save_point(0, "10", "20", "150", "right", True, "45")
        self.assertTrue(saved)
        point = self.app.points[0]
        self.assertEqual((point.x, point.y, point.delay_ms), (10, 20, 150))
        self.assertEqual(point.button, "right")
        self.assertTrue(point.double)
        self.assertEqual(point.hold_ms, 45)
        self.assertIn("Point 1 updated", self.app.var_status.get())

    def test_save_point_rejects_bad_numbers(self):
        self.app.points = [engine.Point(x=1, y=2)]
        with patch.object(gui.messagebox, "showerror") as showerror:
            saved = self.app._save_point(0, "abc", "2", "0", "left", False, "0")
        self.assertFalse(saved)
        self.assertEqual(self.app.points[0].x, 1)
        showerror.assert_called_once()

    def test_saved_settings_keep_point_hold_and_sequence_cap(self):
        self.app.points = [engine.Point(x=1, y=2, delay_ms=10, hold_ms=35)]
        self.app.var_seq_count.set("8")
        settings = self.app.current_settings()
        self.assertEqual(settings["points"][0]["hold_ms"], 35)
        self.assertEqual(settings["sequence_count"], 8)

    def _wait_for_pick(self, timeout=5):
        deadline = time.time() + timeout
        while self.app._pick_active and time.time() < deadline:
            self.root.update()
            time.sleep(0.02)
        self.root.update()
        self.assertFalse(self.app._pick_active, "pick flow did not finish")

    def test_failed_hotkey_rebind_keeps_the_previous_key(self):
        previous = Mock()
        previous.hotkey = "F6"
        self.app.hotkey_listener = previous
        self.app.var_hotkey.set("F8")
        with patch.object(gui.hotkey, "HotkeyListener") as listener_class:
            listener_class.return_value.hotkey = "F8"
            listener_class.return_value.start.side_effect = gui.hotkey.HotkeyError("key taken")
            self.app._start_hotkey()
        previous.stop.assert_not_called()
        self.assertIs(self.app.hotkey_listener, previous)
        self.assertEqual(self.app.var_hotkey.get(), "F6")
        self.assertIn("kept F6", self.app.var_status.get())

    def test_successful_hotkey_rebind_replaces_the_listener(self):
        previous = Mock()
        previous.hotkey = "F6"
        self.app.hotkey_listener = previous
        self.app.var_hotkey.set("F8")
        new = Mock()
        new.hotkey = "F8"
        with patch.object(gui.hotkey, "HotkeyListener", return_value=new):
            self.app._start_hotkey()
        new.start.assert_called_once()
        previous.stop.assert_called_once()
        self.assertIs(self.app.hotkey_listener, new)
        self.assertEqual(self.app.var_hotkey.get(), "F8")
        self.assertIn("F8", self.app.var_status.get())

    def test_reapplying_the_same_hotkey_does_not_regrab(self):
        previous = Mock()
        previous.hotkey = "F6"
        self.app.hotkey_listener = previous
        same = Mock()
        same.hotkey = "F6"
        with patch.object(gui.hotkey, "HotkeyListener", return_value=same):
            self.app._start_hotkey()
        same.start.assert_not_called()
        previous.stop.assert_not_called()
        self.assertIs(self.app.hotkey_listener, previous)

    def test_ipc_raise_request_focuses_the_window(self):
        self.app.start_ipc_poll()
        with patch.object(self.app, "focus_window") as focus:
            self.app.request_focus()
            deadline = time.time() + 2
            while time.time() < deadline and not focus.called:
                self.root.update()
                time.sleep(0.02)
        focus.assert_called_once()

    def _sequence_file(self, points):
        path = os.path.join(self.tmp, "sequence.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(points, handle)
        return path

    def test_move_point_reorders_the_sequence(self):
        self.app.points = [engine.Point(x=1, y=1), engine.Point(x=2, y=2), engine.Point(x=3, y=3)]
        self.app._refresh_points()
        self.app.tree.selection_set(self.app.tree.get_children()[2])
        self.assertTrue(self.app.move_point(-1))
        self.assertEqual([point.x for point in self.app.points], [1, 3, 2])
        self.assertEqual(self.app.tree.index(self.app.tree.selection()[0]), 1)
        self.assertIn("Moved point 3 to 2", self.app.var_status.get())

    def test_move_point_at_the_edge_is_a_no_op(self):
        self.app.points = [engine.Point(x=1, y=1)]
        self.app._refresh_points()
        self.app.tree.selection_set(self.app.tree.get_children()[0])
        self.assertFalse(self.app.move_point(-1))
        self.assertEqual(len(self.app.points), 1)

    def test_duplicate_point_copies_every_field(self):
        self.app.points = [engine.Point(x=5, y=6, delay_ms=70, button="right", double=True, hold_ms=20)]
        self.app._refresh_points()
        self.app.tree.selection_set(self.app.tree.get_children()[0])
        self.assertTrue(self.app.duplicate_point())
        self.assertEqual(len(self.app.points), 2)
        self.assertEqual(
            (self.app.points[1].x, self.app.points[1].hold_ms, self.app.points[1].button),
            (5, 20, "right"),
        )
        self.assertEqual(self.app.tree.index(self.app.tree.selection()[0]), 1)

    def test_export_points_writes_the_cli_format(self):
        self.app.points = [
            engine.Point(x=1, y=2, delay_ms=10, button="right", double=True, hold_ms=5)
        ]
        path = os.path.join(self.tmp, "export.json")
        self.assertTrue(self.app.export_points(path))
        with open(path, "r", encoding="utf-8") as handle:
            self.assertEqual(
                json.load(handle),
                [{"x": 1, "y": 2, "delay_ms": 10, "button": "right",
                  "double": True, "hold_ms": 5}],
            )
        self.assertIn("Exported 1 points", self.app.var_status.get())

    def test_import_points_replaces_after_confirmation(self):
        self.app.points = [engine.Point(x=9, y=9)]
        path = self._sequence_file(
            [{"x": 3, "y": 4, "delay_ms": 25, "hold_ms": 7},
             {"x": 5, "y": 6, "button": "right"}]
        )
        with patch.object(gui.messagebox, "askyesno", return_value=True):
            self.assertTrue(self.app.import_points(path))
        self.assertEqual([(p.x, p.y) for p in self.app.points], [(3, 4), (5, 6)])
        self.assertEqual(self.app.points[0].hold_ms, 7)
        self.assertEqual(self.app.points[1].button, "right")
        self.assertEqual(len(self.app.tree.get_children()), 2)

    def test_import_can_append_instead_of_replacing(self):
        self.app.points = [engine.Point(x=9, y=9)]
        path = self._sequence_file([{"x": 1, "y": 1}])
        self.assertTrue(self.app.import_points(path, replace=False))
        self.assertEqual([(p.x, p.y) for p in self.app.points], [(9, 9), (1, 1)])

    def test_import_reports_invalid_files(self):
        path = self._sequence_file([{"x": -1, "y": 2}])
        with patch.object(gui.messagebox, "showerror") as showerror:
            self.assertFalse(self.app.import_points(path))
        showerror.assert_called_once()
        self.assertEqual(self.app.points, [])

    def test_clear_asks_for_confirmation(self):
        self.app.points = [engine.Point(x=1, y=2)]
        self.app._refresh_points()
        with patch.object(gui.messagebox, "askyesno", return_value=False) as ask:
            self.app.clear_points()
        ask.assert_called_once()
        self.assertEqual(len(self.app.points), 1)

    def test_clear_removes_points_when_confirmed(self):
        self.app.points = [engine.Point(x=1, y=2), engine.Point(x=3, y=4)]
        self.app._refresh_points()
        with patch.object(gui.messagebox, "askyesno", return_value=True):
            self.app.clear_points()
        self.assertEqual(self.app.points, [])
        self.assertEqual(self.app.tree.get_children(), ())
        self.assertEqual(self.app.var_status.get(), "Sequence cleared")

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

    def test_fixed_point_without_hotkey_asks_before_starting(self):
        self.app.hotkey_listener = None
        self.app.var_fixed.set(True)
        self.app.var_x.set("100")
        self.app.var_y.set("120")
        self.app.var_unlimited.set(False)
        self.app.var_count.set("1")
        with patch.object(gui.messagebox, "askyesno", return_value=False) as ask:
            self.app.start()
        ask.assert_called_once()
        self.assertFalse(self.app.engine.running)
        self.assertIn("Cancelled", self.app.var_status.get())

    def test_cursor_mode_without_hotkey_starts_without_asking(self):
        self.app.hotkey_listener = None
        self.app.var_fixed.set(False)
        self.app.var_unlimited.set(False)
        self.app.var_count.set("1")
        self.app.var_millis.set("5")
        with patch.object(gui.messagebox, "askyesno") as ask:
            self.app.start()
            deadline = time.time() + 5
            while self.app.engine.running and time.time() < deadline:
                self.root.update()
                time.sleep(0.01)
            self.app.stop()
        ask.assert_not_called()
        self.assertEqual(self.app.engine.clicks_done, 1)

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
