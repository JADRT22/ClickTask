# -*- coding: utf-8 -*-
"""
ClickTask - test_cli.py
Description: CLI tests: interval/point parsing, sequence files, plan building,
             exit codes and full --dry-run runs (no input is injected).
Author: JADRT22 (https://github.com/JADRT22)
License: MIT
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import backend  # noqa: E402
import cli  # noqa: E402
import engine  # noqa: E402


class ParseIntervalTests(unittest.TestCase):
    def test_units(self):
        cases = {
            "100": 100,
            "100ms": 100,
            "250MS": 250,
            "1s": 1000,
            "1.5s": 1500,
            "2m": 120000,
            "1h": 3600000,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(cli.parse_interval(text), expected)

    def test_invalid_values(self):
        for text in ("", "abc", "0", "0.5ms", "-5", "10ss"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    cli.parse_interval(text)


class ParsePointTests(unittest.TestCase):
    def test_separators(self):
        self.assertEqual(cli.parse_point("800,600"), (800, 600))
        self.assertEqual(cli.parse_point("800x600"), (800, 600))
        self.assertEqual(cli.parse_point(" 800 600 "), (800, 600))

    def test_invalid_values(self):
        for text in ("", "abc", "800", "-1,5", "1,2,3"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    cli.parse_point(text)


class SequenceFileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()

    def write(self, payload):
        path = os.path.join(self.directory, "points.json")
        with open(path, "w", encoding="utf-8") as handle:
            if isinstance(payload, str):
                handle.write(payload)
            else:
                json.dump(payload, handle)
        return path

    def test_list_format(self):
        path = self.write([{"x": 1, "y": 2, "delay_ms": 30}, {"x": 3, "y": 4}])
        points = cli.load_points(path)
        self.assertEqual([(p.x, p.y, p.delay_ms) for p in points], [(1, 2, 30), (3, 4, 0)])

    def test_dict_format(self):
        path = self.write({"points": [{"x": 5, "y": 6, "button": "right", "double": True}]})
        points = cli.load_points(path)
        self.assertEqual(points[0].button, "right")
        self.assertTrue(points[0].double)

    def test_invalid_files(self):
        for payload in ("{bad", "[]", "{}", [{"y": 1}], [{"x": 1, "y": 2}] * 0):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    cli.load_points(self.write(payload))

    def test_missing_file(self):
        with self.assertRaises(ValueError):
            cli.load_points(os.path.join(self.directory, "nope.json"))


class PlanBuildingTests(unittest.TestCase):
    def test_click_plan(self):
        args = cli.build_parser().parse_args(
            ["click", "--interval", "1.5s", "--count", "4", "--button", "right",
             "--double", "--hold", "10", "--at", "640,480"]
        )
        plan = cli.plan_from_args(args)
        self.assertEqual(plan.mode, engine.INTERVAL_MODE)
        self.assertEqual(plan.interval_ms, 1500)
        self.assertEqual(plan.count, 4)
        self.assertEqual(plan.button, "right")
        self.assertTrue(plan.double)
        self.assertEqual(plan.hold_ms, 10)
        self.assertEqual(plan.position, (640, 480))

    def test_sequence_plan_uses_interval_as_default_delay(self):
        directory = tempfile.mkdtemp()
        path = os.path.join(directory, "points.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump([{"x": 1, "y": 1}, {"x": 2, "y": 2, "delay_ms": 5}], handle)
        args = cli.build_parser().parse_args(["seq", path, "--interval", "20ms", "--loops", "3"])
        plan = cli.plan_from_args(args)
        self.assertEqual(plan.mode, engine.SEQUENCE_MODE)
        self.assertEqual(plan.loops, 3)
        self.assertEqual([p.delay_ms for p in plan.points], [20, 5])

    def test_invalid_hold_is_a_usage_error(self):
        self.assertEqual(cli.main(["click", "--hold", "abc"]), cli.EXIT_USAGE)


class DryRunTests(unittest.TestCase):
    def capture(self, argv):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_interval_run(self):
        code, out, _err = self.capture(
            ["click", "--interval", "1ms", "--count", "3", "--dry-run"]
        )
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(len(out.strip().splitlines()), 3)
        self.assertIn("click left (single)", out)

    def test_sequence_run(self):
        directory = tempfile.mkdtemp()
        path = os.path.join(directory, "points.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump([{"x": 1, "y": 1}, {"x": 2, "y": 2}], handle)
        code, out, _err = self.capture(
            ["seq", path, "--loops", "2", "--interval", "1ms", "--dry-run"]
        )
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(len(out.strip().splitlines()), 4)

    def test_invalid_interval_is_a_usage_error(self):
        code, _out, err = self.capture(["click", "--interval", "nope"])
        self.assertEqual(code, cli.EXIT_USAGE)
        self.assertIn("invalid interval", err)

    def test_backend_failure_exit_code(self):
        with patch.object(
            backend, "make_backend", side_effect=backend.BackendError("no display")
        ):
            code, _out, err = self.capture(["click", "--count", "1", "--dry-run"])
        self.assertEqual(code, cli.EXIT_BACKEND)
        self.assertIn("no display", err)

    def test_no_command_prints_help(self):
        code, out, _err = self.capture([])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("interval auto clicker", out.lower())

    def test_version(self):
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                cli.main(["--version"])
        self.assertEqual(raised.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
