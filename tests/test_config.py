# -*- coding: utf-8 -*-
"""
ClickTask - test_config.py
Description: Settings tests: defaults, validation of corrupted input, XDG path
             handling and atomic save/load round-trips in a temp directory.
Author: JADRT22 (https://github.com/JADRT22)
License: MIT
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import config  # noqa: E402


class NormalizeTests(unittest.TestCase):
    def test_empty_input_yields_defaults(self):
        self.assertEqual(config.normalize({}), config.DEFAULTS)
        self.assertEqual(config.normalize(None), config.DEFAULTS)

    def test_invalid_button_falls_back(self):
        self.assertEqual(config.normalize({"button": "thumb"})["button"], "left")

    def test_interval_bounds(self):
        self.assertEqual(config.normalize({"interval_ms": 0})["interval_ms"], 100)
        self.assertEqual(config.normalize({"interval_ms": "abc"})["interval_ms"], 100)
        self.assertEqual(config.normalize({"interval_ms": 250})["interval_ms"], 250)
        self.assertEqual(
            config.normalize({"interval_ms": 10 ** 12})["interval_ms"], config.MAX_INTERVAL_MS
        )

    def test_position_validation(self):
        self.assertEqual(config.normalize({"position": [10, 20]})["position"], [10, 20])
        self.assertIsNone(config.normalize({"position": [-1, 20]})["position"])
        self.assertIsNone(config.normalize({"position": "10,20"})["position"])
        self.assertIsNone(config.normalize({"position": [1]})["position"])

    def test_blank_hotkey_falls_back(self):
        self.assertEqual(config.normalize({"hotkey": "   "})["hotkey"], "F6")

    def test_points_are_normalized_and_junk_dropped(self):
        settings = config.normalize(
            {
                "points": [
                    {"x": 1, "y": 2, "delay_ms": 50, "button": "right", "double": True},
                    {"x": 3, "y": 4, "button": "thumb"},
                    "not a point",
                ]
            }
        )
        self.assertEqual(len(settings["points"]), 2)
        self.assertEqual(settings["points"][0]["button"], "right")
        self.assertEqual(settings["points"][1]["button"], "")

    def test_point_hold_is_kept_and_clamped(self):
        settings = config.normalize(
            {
                "points": [
                    {"x": 1, "y": 2, "hold_ms": 25},
                    {"x": 3, "y": 4, "hold_ms": -5},
                    {"x": 5, "y": 6, "hold_ms": 10 ** 9},
                ]
            }
        )
        self.assertEqual(settings["points"][0]["hold_ms"], 25)
        self.assertEqual(settings["points"][1]["hold_ms"], 0)
        self.assertEqual(settings["points"][2]["hold_ms"], 60000)

    def test_sequence_count_is_validated(self):
        self.assertEqual(config.normalize({})["sequence_count"], 0)
        self.assertEqual(config.normalize({"sequence_count": 12})["sequence_count"], 12)
        self.assertEqual(config.normalize({"sequence_count": -3})["sequence_count"], 0)


class PathTests(unittest.TestCase):
    def test_xdg_config_home_is_respected(self):
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": "/tmp/xdg-test"}, clear=False):
            self.assertEqual(
                config.config_path(), "/tmp/xdg-test/clicktask/config.json"
            )

    def test_fallback_path(self):
        environment = dict(os.environ)
        environment.pop("XDG_CONFIG_HOME", None)
        with patch.dict(os.environ, environment, clear=True):
            expected = os.path.join(os.path.expanduser("~"), ".config", "clicktask", "config.json")
            self.assertEqual(config.config_path(), expected)


class SaveLoadTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.path = os.path.join(self.directory, "nested", "config.json")

    def test_round_trip(self):
        settings = config.normalize({"interval_ms": 250, "button": "right", "count": 7})
        self.assertEqual(config.save(settings, self.path), self.path)
        self.assertTrue(os.path.isfile(self.path))
        loaded = config.load(self.path)
        self.assertEqual(loaded["interval_ms"], 250)
        self.assertEqual(loaded["button"], "right")
        self.assertEqual(loaded["count"], 7)

    def test_save_leaves_no_temp_file(self):
        config.save({"interval_ms": 5}, self.path)
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["config.json"])

    def test_corrupt_file_loads_defaults(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertEqual(config.load(self.path), config.DEFAULTS)

    def test_missing_file_loads_defaults(self):
        self.assertEqual(config.load(self.path), config.DEFAULTS)

    def test_partial_file_is_completed(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"button": "middle"}, handle)
        loaded = config.load(self.path)
        self.assertEqual(loaded["button"], "middle")
        self.assertEqual(loaded["interval_ms"], config.DEFAULTS["interval_ms"])

    def test_save_failure_returns_none(self):
        blocker = os.path.join(self.directory, "file")
        with open(blocker, "w", encoding="utf-8") as handle:
            handle.write("x")
        self.assertIsNone(config.save({}, os.path.join(blocker, "config.json")))


if __name__ == "__main__":
    unittest.main()
