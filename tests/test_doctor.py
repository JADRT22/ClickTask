# -*- coding: utf-8 -*-
"""
ClickTask - test_doctor.py
Description: `clicktask doctor` tests: report formatting and exit codes, the
             managed/unmanaged install check, the timer check and the settings
             check. Display probes are not exercised here; CI has no X server.
Author: JADRT22 (https://github.com/JADRT22)
License: MIT
"""

import io
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import doctor  # noqa: E402
import installer  # noqa: E402


class ReportTests(unittest.TestCase):
    def render(self, entries):
        out = io.StringIO()
        code = doctor.report(entries, out=out)
        return code, out.getvalue()

    def test_all_ok_returns_zero(self):
        code, text = self.render([doctor.entry(doctor.OK, "python", "3.12.0")])
        self.assertEqual(code, 0)
        self.assertIn("[ok] python — 3.12.0", text)
        self.assertIn("All checks passed.", text)

    def test_warnings_do_not_fail(self):
        code, text = self.render([doctor.entry(doctor.WARN, "timer", "missing")])
        self.assertEqual(code, 0)
        self.assertIn("1 warning(s)", text)

    def test_a_failure_returns_one(self):
        code, text = self.render(
            [
                doctor.entry(doctor.OK, "python", "3.12.0"),
                doctor.entry(doctor.FAIL, "DISPLAY", "not set"),
            ]
        )
        self.assertEqual(code, 1)
        self.assertIn("1 check(s) failed", text)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.prefix = os.path.join(self.tmp, "ClickTask")
        os.makedirs(os.path.join(self.prefix, "src"))
        with open(os.path.join(self.prefix, "src", "version.py"), "w", encoding="utf-8") as handle:
            handle.write('VERSION = "1.1.5"\n')
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.environment = patch.dict(
            os.environ,
            {
                "HOME": self.home,
                "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
                "XDG_DATA_HOME": os.path.join(self.home, ".local", "share"),
                "CLICKTASK_DESKTOP_DIR": os.path.join(self.home, "Desktop"),
                "CLICKTASK_SKIP_SYSTEMCTL": "1",
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_unmanaged_tree_is_a_warning(self):
        result = doctor.check_install(self.prefix)
        self.assertEqual(result["level"], doctor.WARN)
        self.assertIn("not a managed install", result["detail"])

    def test_managed_tree_with_shortcuts_is_ok(self):
        installer.write_marker(self.prefix, "1.1.5")
        launcher = installer.launcher_path()
        menu = installer.desktop_entry_path()
        for path in (launcher, menu):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").close()
        result = doctor.check_install(self.prefix)
        self.assertEqual(result["level"], doctor.OK)
        self.assertIn("v1.1.5", result["detail"])

    def test_missing_timer_is_a_warning(self):
        result = doctor.check_timer()
        self.assertEqual(result["level"], doctor.WARN)
        self.assertIn("not installed", result["detail"])

    def test_settings_check_names_the_path(self):
        result = doctor.check_config()
        self.assertEqual(result["level"], doctor.OK)
        self.assertIn("clicktask", result["detail"])


if __name__ == "__main__":
    unittest.main()
