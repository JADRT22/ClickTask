# -*- coding: utf-8 -*-
"""
ClickTask - test_installer.py
Description: Desktop integration tests: launcher, menu entry, desktop shortcut,
             icon, update timer, refresh after an update and uninstall. Every
             path is redirected to a temp $HOME, and systemd/cache tools are
             skipped, so no real session file is touched.
Author: JADRT22 (https://github.com/JADRT22)
License: MIT
"""

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import installer  # noqa: E402


class InstallerTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        self.desktop = os.path.join(self.home, "Desktop")
        os.makedirs(self.desktop)
        self.environment = patch.dict(
            os.environ,
            {
                "HOME": self.home,
                "XDG_DATA_HOME": os.path.join(self.home, ".local", "share"),
                "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
                "CLICKTASK_DESKTOP_DIR": self.desktop,
                "CLICKTASK_SKIP_SYSTEMCTL": "1",
                "CLICKTASK_SKIP_CACHES": "1",
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

        self.prefix = os.path.join(self.tmp, "ClickTask")
        os.makedirs(os.path.join(self.prefix, "src"))
        self._write(os.path.join(self.prefix, "src", "version.py"), 'VERSION = "1.1.0"\n')
        self._write(os.path.join(self.prefix, "src", "main.py"), "print('hi')\n")

    def _write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def read(self, path):
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()


class InstallTests(InstallerTestBase):
    def test_install_creates_launcher_menu_desktop_icon_and_marker(self):
        installer.install(self.prefix)

        launcher = installer.launcher_path()
        self.assertTrue(os.path.isfile(launcher))
        self.assertTrue(os.access(launcher, os.X_OK))
        self.assertIn(self.prefix, self.read(launcher))
        self.assertIn("src/main.py", self.read(launcher))

        menu = installer.desktop_entry_path()
        self.assertTrue(os.path.isfile(menu))
        entry = self.read(menu)
        self.assertIn("Name=ClickTask", entry)
        self.assertIn(f'Exec="{launcher}"', entry)
        self.assertIn("Icon=clicktask", entry)
        self.assertIn("Categories=Utility;", entry)
        self.assertIn("StartupWMClass=ClickTask", entry)
        self.assertIn("X-ClickTask-Version=1.1.0", entry)
        self.assertIn("clicker", entry.lower())

        shortcut = installer.desktop_shortcut_path()
        self.assertTrue(os.path.isfile(shortcut))
        self.assertTrue(os.access(shortcut, os.X_OK))

        for icon in installer.icon_paths():
            self.assertTrue(os.path.isfile(icon), icon)

        marker = json.loads(self.read(installer.marker_path(self.prefix)))
        self.assertEqual(marker["version"], "1.1.0")
        self.assertTrue(marker["desktop"])
        self.assertTrue(marker["autoupdate"])
        self.assertTrue(installer.is_managed(self.prefix))

    def test_launcher_is_valid_shell(self):
        installer.install(self.prefix)
        result = subprocess.run(
            ["bash", "-n", installer.launcher_path()], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_exec_path_quotes_spaces(self):
        quoted = installer._exec_path("/tmp/a b/clicktask")
        self.assertEqual(quoted, '"/tmp/a b/clicktask"')

    def test_no_desktop_shortcut_choice_survives_refresh(self):
        installer.install(self.prefix, desktop=False)
        self.assertFalse(os.path.exists(installer.desktop_shortcut_path()))
        self.assertTrue(os.path.exists(installer.desktop_entry_path()))

        self._write(os.path.join(self.prefix, "src", "version.py"), 'VERSION = "2.0.0"\n')
        installer.refresh(self.prefix)
        self.assertFalse(os.path.exists(installer.desktop_shortcut_path()))
        self.assertIn("X-ClickTask-Version=2.0.0", self.read(installer.desktop_entry_path()))

    def test_install_is_idempotent(self):
        installer.install(self.prefix)
        installer.install(self.prefix)
        self.assertTrue(os.path.exists(installer.launcher_path()))

    def test_autoupdate_timer_units(self):
        installer.install(self.prefix)
        timer = os.path.join(installer.systemd_dir(), f"{installer.TIMER_NAME}.timer")
        service = os.path.join(installer.systemd_dir(), f"{installer.TIMER_NAME}.service")
        self.assertTrue(os.path.isfile(timer))
        self.assertTrue(os.path.isfile(service))
        self.assertIn("OnCalendar=daily", self.read(timer))
        self.assertIn("update --quiet", self.read(service))

    def test_no_autoupdate_removes_units(self):
        installer.install(self.prefix)
        installer.install(self.prefix, autoupdate=False)
        timer = os.path.join(installer.systemd_dir(), f"{installer.TIMER_NAME}.timer")
        self.assertFalse(os.path.exists(timer))
        self.assertFalse(
            json.loads(self.read(installer.marker_path(self.prefix)))["autoupdate"]
        )


class UninstallTests(InstallerTestBase):
    def test_uninstall_removes_integration_and_keeps_settings(self):
        installer.install(self.prefix)
        config = os.path.join(installer.config_home(), "clicktask", "config.json")
        self._write(config, "{}")

        installer.uninstall(self.prefix)

        for path in (
            installer.launcher_path(),
            installer.desktop_entry_path(),
            installer.desktop_shortcut_path(),
            installer.marker_path(self.prefix),
            *installer.icon_paths(),
        ):
            self.assertFalse(os.path.exists(path), path)
        self.assertTrue(os.path.exists(config))

    def test_purge_removes_settings(self):
        installer.install(self.prefix)
        config = os.path.join(installer.config_home(), "clicktask", "config.json")
        self._write(config, "{}")

        installer.uninstall(self.prefix, purge=True)
        self.assertFalse(os.path.exists(config))


class StatusTests(InstallerTestBase):
    def test_status_reports_installed_paths(self):
        installer.install(self.prefix)
        with patch("sys.stdout") as stdout:
            code = installer.main(["status", "--prefix", self.prefix])
        self.assertEqual(code, 0)
        printed = "".join(str(call.args[0]) for call in stdout.write.call_args_list)
        self.assertIn("managed  : yes", printed)
        self.assertIn("menu     : yes", printed)


if __name__ == "__main__":
    unittest.main()
