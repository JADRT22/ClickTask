# -*- coding: utf-8 -*-
"""
ClickTask - test_updater.py
Description: Update tests: version comparison, GitHub release parsing, tarball
             safety, an end-to-end apply against a fake release archive, the
             managed-install guard and the pip refresh. Network and systemd are
             stubbed, so the suite never leaves the temp folder.
Author: JADRT22 (https://github.com/JADRT22)
License: MIT
"""

import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import installer  # noqa: E402
import updater  # noqa: E402


class VersionTests(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(updater.parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(updater.parse_version("1.2"), (1, 2, 0))
        self.assertEqual(updater.parse_version("  2 "), (2, 0, 0))

    def test_parse_version_rejects_junk(self):
        for value in ("", None, "banana", "v"):
            with self.subTest(value=value):
                with self.assertRaises(updater.UpdateError):
                    updater.parse_version(value)

    def test_is_newer(self):
        self.assertTrue(updater.is_newer("1.2.0", "1.1.9"))
        self.assertTrue(updater.is_newer("v2.0.0", "1.99.99"))
        self.assertFalse(updater.is_newer("1.1.0", "1.1.0"))
        self.assertFalse(updater.is_newer("1.0.9", "1.1.0"))


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.environment = patch.dict(
            os.environ, {"HOME": self.tmp, "XDG_CACHE_HOME": os.path.join(self.tmp, "cache")}
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def payload(self, version="1.2.0"):
        return json.dumps(
            {
                "tag_name": f"v{version}",
                "tarball_url": "https://example.invalid/release.tar.gz",
                "html_url": "https://example.invalid/release",
                "body": "notes",
            }
        ).encode()

    def test_fetch_writes_the_cache(self):
        release = updater.fetch_latest_release(fetch=lambda url, timeout: self.payload())
        self.assertEqual(release["version"], "1.2.0")
        cached = updater.read_cache()
        self.assertEqual(cached["version"], "1.2.0")
        self.assertTrue(os.path.isfile(updater.cache_path()))

    def test_fresh_cache_skips_the_network(self):
        updater.write_cache(
            {"version": "1.2.0", "tag": "v1.2.0", "tarball_url": "https://x/tar.gz"}
        )
        calls = []

        def fetch(url, timeout):
            calls.append(url)
            return self.payload("9.9.9")

        release = updater.fetch_latest_release(fetch=fetch)
        self.assertEqual(release["version"], "1.2.0")
        self.assertTrue(release.get("cached"))
        self.assertEqual(calls, [])

    def test_expired_cache_hits_the_network(self):
        updater.write_cache(
            {"version": "1.2.0", "tag": "v1.2.0", "tarball_url": "https://x/tar.gz"}
        )
        release = updater.fetch_latest_release(
            fetch=lambda url, timeout: self.payload("1.3.0"), max_age=-1
        )
        self.assertEqual(release["version"], "1.3.0")
        self.assertEqual(updater.read_cache()["version"], "1.3.0")

    def test_manual_check_bypasses_the_cache(self):
        updater.write_cache(
            {"version": "1.2.0", "tag": "v1.2.0", "tarball_url": "https://x/tar.gz"}
        )
        release = updater.fetch_latest_release(
            fetch=lambda url, timeout: self.payload("1.3.0"), use_cache=False
        )
        self.assertEqual(release["version"], "1.3.0")

    def test_corrupt_cache_is_ignored(self):
        os.makedirs(os.path.dirname(updater.cache_path()), exist_ok=True)
        with open(updater.cache_path(), "w", encoding="utf-8") as handle:
            handle.write("{bad")
        self.assertIsNone(updater.read_cache())
        release = updater.fetch_latest_release(fetch=lambda url, timeout: self.payload())
        self.assertEqual(release["version"], "1.2.0")


class GithubTests(unittest.TestCase):
    def setUp(self):
        # Never read or write the user's real update cache from tests.
        self.tmp = tempfile.mkdtemp()
        self.environment = patch.dict(
            os.environ,
            {"XDG_CACHE_HOME": os.path.join(self.tmp, "cache")},
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def payload(self, **overrides):
        data = {
            "tag_name": "v1.2.0",
            "tarball_url": "https://example.invalid/release.tar.gz",
            "html_url": "https://example.invalid/release",
            "name": "ClickTask 1.2.0",
            "body": "notes",
        }
        data.update(overrides)
        return json.dumps(data).encode()

    def test_fetch_latest_release(self):
        release = updater.fetch_latest_release(
            fetch=lambda url, timeout: self.payload(), use_cache=False
        )
        self.assertEqual(release["version"], "1.2.0")
        self.assertEqual(release["tag"], "v1.2.0")
        self.assertEqual(release["tarball_url"], "https://example.invalid/release.tar.gz")

    def test_fetch_rejects_missing_fields(self):
        with self.assertRaises(updater.UpdateError):
            updater.fetch_latest_release(
                fetch=lambda url, timeout: self.payload(tag_name=""), use_cache=False
            )

    def test_fetch_rejects_bad_json(self):
        with self.assertRaises(updater.UpdateError):
            updater.fetch_latest_release(
                fetch=lambda url, timeout: b"not json", use_cache=False
            )

    def test_check_for_update(self):
        with patch.object(updater, "installed_version", return_value="1.1.0"):
            newer = updater.check_for_update(
                fetch=lambda url, timeout: self.payload(), use_cache=False
            )
            same = updater.check_for_update(
                current="1.2.0",
                fetch=lambda url, timeout: self.payload(),
                use_cache=False,
            )
        self.assertEqual(newer["version"], "1.2.0")
        self.assertIsNone(same)


class ApplyTests(unittest.TestCase):
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
        self.write("src/version.py", 'VERSION = "1.1.0"\n')
        self.write("src/main.py", "print('old')\n")
        self.write("src/legacy.py", "# removed in the new release\n")
        self.write("README.md", "# old readme\n")
        self.write("requirements.txt", "python-xlib==0.33\n")
        installer.write_marker(self.prefix, "1.1.0")

    def write(self, relative, text):
        path = os.path.join(self.prefix, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def read(self, relative):
        with open(os.path.join(self.prefix, relative), "r", encoding="utf-8") as handle:
            return handle.read()

    def tarball(self, version="2.0.0", files=None, requirements=None):
        contents = {
            "src/version.py": f'VERSION = "{version}"\n',
            "src/main.py": "print('new')\n",
            "README.md": f"# ClickTask {version}\n",
            "assets/clicktask.svg": "<svg/>\n",
        }
        if requirements is not None:
            contents["requirements.txt"] = requirements
        contents.update(files or {})
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            for name, text in contents.items():
                payload = text.encode("utf-8")
                info = tarfile.TarInfo(f"ClickTask-release/{name}")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
        return buffer.getvalue()

    def release(self, version="2.0.0", **extra):
        data = {"version": version, "tag": f"v{version}", "tarball_url": "https://example.invalid/tar.gz"}
        data.update(extra)
        return data

    def apply(self, archive, **kwargs):
        return updater.apply_release(
            kwargs.pop("release", self.release()),
            root=self.prefix,
            fetch=lambda url, timeout: archive,
            **kwargs,
        )

    def test_apply_replaces_files_and_drops_removed_modules(self):
        result = self.apply(self.tarball("2.0.0"))

        self.assertTrue(result["updated"])
        self.assertEqual((result["from"], result["to"]), ("1.1.0", "2.0.0"))
        self.assertIn('VERSION = "2.0.0"', self.read("src/version.py"))
        self.assertIn("new", self.read("src/main.py"))
        self.assertTrue(os.path.exists(os.path.join(self.prefix, "src", "main.py")))
        self.assertFalse(os.path.exists(os.path.join(self.prefix, "src", "legacy.py")))
        self.assertIn("2.0.0", self.read("README.md"))
        self.assertFalse(os.path.exists(os.path.join(self.prefix, ".update.lock.tmp")))

        marker = installer.read_marker(self.prefix)
        self.assertEqual(marker["version"], "2.0.0")

        menu = installer.desktop_entry_path()
        with open(menu, "r", encoding="utf-8") as handle:
            self.assertIn("X-ClickTask-Version=2.0.0", handle.read())

    def test_same_version_is_a_no_op_without_force(self):
        result = self.apply(self.tarball("1.1.0"), release=self.release("1.1.0"))
        self.assertFalse(result["updated"])
        self.assertIn("old", self.read("src/main.py"))

    def test_force_reinstalls_the_same_version(self):
        result = self.apply(self.tarball("1.1.0"), release=self.release("1.1.0"), force=True)
        self.assertTrue(result["updated"])
        self.assertIn("new", self.read("src/main.py"))

    def test_unmanaged_tree_is_refused(self):
        os.remove(installer.marker_path(self.prefix))
        with self.assertRaises(updater.UpdateError):
            self.apply(self.tarball("2.0.0"))
        self.assertIn("old", self.read("src/main.py"))

    def test_archive_escaping_the_temp_folder_is_rejected(self):
        archive = self.tarball("2.0.0", files={"src/../../../escape.txt": "bad"})
        with self.assertRaises(updater.UpdateError):
            self.apply(archive)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "escape.txt")))
        self.assertIn("old", self.read("src/main.py"))

    def test_failed_swap_restores_the_previous_files(self):
        real_replace = os.replace
        calls = {"swap": 0}

        def flaky(source, target):
            if "new" in str(source) and ".clicktask-stage-" in str(source):
                calls["swap"] += 1
                if calls["swap"] == 2:
                    raise OSError("disk full")
            return real_replace(source, target)

        with patch.object(updater.os, "replace", side_effect=flaky):
            with self.assertRaises(updater.UpdateError):
                self.apply(self.tarball("2.0.0"))

        self.assertIn("old", self.read("src/main.py"))
        self.assertIn('VERSION = "1.1.0"', self.read("src/version.py"))
        self.assertTrue(os.path.exists(os.path.join(self.prefix, "src", "legacy.py")))
        self.assertEqual(installer.read_marker(self.prefix)["version"], "1.1.0")

    def test_archive_without_src_is_rejected(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            payload = b"hello"
            info = tarfile.TarInfo("ClickTask/README.md")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        with self.assertRaises(updater.UpdateError):
            self.apply(buffer.getvalue())

    def test_requirements_change_runs_pip(self):
        pip = os.path.join(self.prefix, ".venv", "bin", "pip")
        os.makedirs(os.path.dirname(pip), exist_ok=True)
        open(pip, "w").close()
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            return SimpleNamespace(returncode=0, stderr="")

        result = self.apply(
            self.tarball("2.0.0", requirements="python-xlib==0.34\n"),
            pip_install=runner,
        )
        self.assertTrue(result["updated"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], pip)

    def test_checksum_asset_is_verified_before_swapping(self):
        import hashlib

        archive = self.tarball("2.0.0")
        digest = hashlib.sha256(archive).hexdigest()
        sums = f"{digest}  ClickTask-v2.0.0.tar.gz\n".encode()
        release = self.release("2.0.0")
        release["assets"] = [
            {"name": "ClickTask-v2.0.0.tar.gz", "url": "https://example.invalid/asset.tar.gz"},
            {"name": "SHA256SUMS", "url": "https://example.invalid/SHA256SUMS"},
        ]

        def fetch(url, timeout):
            return sums if url.endswith("SHA256SUMS") else archive

        result = updater.apply_release(release, root=self.prefix, fetch=fetch)
        self.assertTrue(result["updated"])
        self.assertEqual(result["to"], "2.0.0")

    def test_checksum_mismatch_keeps_the_old_tree(self):
        archive = self.tarball("2.0.0")
        sums = f"{'0' * 64}  ClickTask-v2.0.0.tar.gz\n".encode()
        release = self.release("2.0.0")
        release["assets"] = [
            {"name": "ClickTask-v2.0.0.tar.gz", "url": "https://example.invalid/asset.tar.gz"},
            {"name": "SHA256SUMS", "url": "https://example.invalid/SHA256SUMS"},
        ]

        def fetch(url, timeout):
            return sums if url.endswith("SHA256SUMS") else archive

        with self.assertRaises(updater.UpdateError):
            updater.apply_release(release, root=self.prefix, fetch=fetch)
        self.assertIn("old", self.read("src/main.py"))
        self.assertIn('VERSION = "1.1.0"', self.read("src/version.py"))

    def test_release_without_assets_falls_back_to_the_tarball(self):
        result = self.apply(self.tarball("2.0.0"))
        self.assertTrue(result["updated"])

    def _signing_key(self, name="release-key"):
        import shutil
        import subprocess

        if not shutil.which("ssh-keygen"):
            self.skipTest("ssh-keygen is not available")
        path = os.path.join(self.tmp, name)
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "clicktask", "-f", path],
            check=True,
            capture_output=True,
        )
        with open(path + ".pub", "r", encoding="utf-8") as handle:
            public = " ".join(handle.read().split()[:2])
        return path, public

    def _signed_release(self, key, version="2.0.0"):
        import hashlib
        import subprocess

        archive = self.tarball(version)
        name = f"ClickTask-v{version}.tar.gz"
        digest = hashlib.sha256(archive).hexdigest()
        sums = f"{digest}  {name}\n".encode("utf-8")
        sums_path = os.path.join(self.tmp, "SHA256SUMS")
        with open(sums_path, "wb") as handle:
            handle.write(sums)
        subprocess.run(
            ["ssh-keygen", "-Y", "sign", "-f", key, "-n", "clicktask", sums_path],
            check=True,
            capture_output=True,
        )
        with open(sums_path + ".sig", "rb") as handle:
            signature = handle.read()
        release = self.release(version)
        release["assets"] = [
            {"name": name, "url": "https://example.invalid/asset.tar.gz"},
            {"name": "SHA256SUMS", "url": "https://example.invalid/SHA256SUMS"},
            {"name": "SHA256SUMS.sig", "url": "https://example.invalid/SHA256SUMS.sig"},
        ]

        def fetch(url, timeout):
            if url.endswith("SHA256SUMS.sig"):
                return signature
            if url.endswith("SHA256SUMS"):
                return sums
            return archive

        return release, fetch

    def test_signed_release_with_the_pinned_key_is_installed(self):
        key, public = self._signing_key()
        release, fetch = self._signed_release(key)
        result = updater.apply_release(
            release, root=self.prefix, fetch=fetch, signer_key=public
        )
        self.assertTrue(result["updated"])
        self.assertIn('VERSION = "2.0.0"', self.read("src/version.py"))

    def test_signature_from_another_key_is_rejected(self):
        key, _ = self._signing_key()
        _, other_public = self._signing_key("other-key")
        release, fetch = self._signed_release(key)
        with self.assertRaises(updater.UpdateError):
            updater.apply_release(
                release, root=self.prefix, fetch=fetch, signer_key=other_public
            )
        self.assertIn("old", self.read("src/main.py"))

    def test_unsigned_release_is_rejected_once_a_key_is_pinned(self):
        archive = self.tarball("2.0.0")
        release = self.release("2.0.0")
        release["assets"] = [
            {"name": "ClickTask-v2.0.0.tar.gz", "url": "https://example.invalid/asset.tar.gz"},
            {"name": "SHA256SUMS", "url": "https://example.invalid/SHA256SUMS"},
        ]
        digest = __import__("hashlib").sha256(archive).hexdigest()
        sums = f"{digest}  ClickTask-v2.0.0.tar.gz\n".encode("utf-8")

        def fetch(url, timeout):
            return sums if url.endswith("SHA256SUMS") else archive

        with self.assertRaises(updater.UpdateError):
            updater.apply_release(
                release, root=self.prefix, fetch=fetch, signer_key="ssh-ed25519 AAAA"
            )
        self.assertIn("old", self.read("src/main.py"))

    def test_rollback_restores_the_previous_tree(self):
        self.apply(self.tarball("2.0.0"))
        self.assertTrue(os.path.isdir(os.path.join(self.prefix, updater.PREVIOUS_DIR)))

        result = updater.rollback(self.prefix)

        self.assertEqual((result["from"], result["to"]), ("2.0.0", "1.1.0"))
        self.assertIn('VERSION = "1.1.0"', self.read("src/version.py"))
        self.assertIn("old", self.read("src/main.py"))
        self.assertTrue(os.path.exists(os.path.join(self.prefix, "src", "legacy.py")))
        self.assertEqual(installer.read_marker(self.prefix)["version"], "1.1.0")
        self.assertFalse(os.path.exists(os.path.join(self.prefix, updater.PREVIOUS_DIR)))

    def test_rollback_without_a_backup_is_reported(self):
        with self.assertRaises(updater.UpdateError):
            updater.rollback(self.prefix)

    def test_pip_failure_is_reported(self):
        pip = os.path.join(self.prefix, ".venv", "bin", "pip")
        os.makedirs(os.path.dirname(pip), exist_ok=True)
        open(pip, "w").close()

        with self.assertRaises(updater.UpdateError):
            self.apply(
                self.tarball("2.0.0", requirements="python-xlib==9.9\n"),
                pip_install=lambda command, **kwargs: SimpleNamespace(
                    returncode=1, stderr="boom"
                ),
            )


if __name__ == "__main__":
    unittest.main()
