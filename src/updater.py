# -*- coding: utf-8 -*-
"""
ClickTask - updater.py
Description: Self-update from GitHub releases. Checks the latest release tag,
             downloads its tarball into a temporary directory, swaps the code in
             an installed tree only after the download and the verification
             succeed, and leaves the venv and the user settings untouched. Stays
             on the standard library so it works before any dependency exists.
Author: JADRT22 (https://github.com/JADRT22)
License: MIT
"""

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request

import installer
from version import REPOSITORY, VERSION

API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
USER_AGENT = f"ClickTask/{VERSION} (+https://github.com/{REPOSITORY})"
TIMEOUT = 15
MAX_TARBALL_BYTES = 50 * 1024 * 1024

# Top-level entries an update may replace. Everything else (`.venv`, marker,
# lock file) is owned by the local install and is never touched.
MANAGED_ITEMS = (
    "src",
    "tools",
    "docs",
    "assets",
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "requirements.txt",
    "run.sh",
)


class UpdateError(RuntimeError):
    """A check or an update could not be completed."""


# --- versions ------------------------------------------------------------


def parse_version(text):
    """Parse 'v1.2.3' / '1.2' into a comparable tuple."""
    match = re.match(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(text or ""))
    if not match:
        raise UpdateError(f"unrecognised version: {text!r}")
    return tuple(int(part or 0) for part in match.groups())


def is_newer(remote, local):
    return parse_version(remote) > parse_version(local)


def installed_root():
    return installer.module_root()


def installed_version(root=None):
    return installer.read_version(root or installed_root())


def is_managed(root=None):
    return installer.is_managed(root or installed_root())


# --- GitHub --------------------------------------------------------------


def _http_get(url, timeout=TIMEOUT):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json, application/octet-stream",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_latest_release(fetch=None, timeout=TIMEOUT):
    """Return {version, tag, tarball_url, html_url, notes} for the latest release."""
    fetch = fetch or _http_get
    try:
        payload = fetch(API_URL, timeout)
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"GitHub returned HTTP {exc.code} for the latest release") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpdateError(f"could not reach GitHub: {exc}") from exc
    try:
        data = json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else payload)
    except (UnicodeDecodeError, ValueError) as exc:
        raise UpdateError(f"GitHub sent an unexpected response: {exc}") from exc
    if not isinstance(data, dict) or not data.get("tag_name") or not data.get("tarball_url"):
        raise UpdateError("the latest release has no tag or tarball")
    tag = str(data["tag_name"])
    return {
        "version": tag.lstrip("vV"),
        "tag": tag,
        "tarball_url": data["tarball_url"],
        "html_url": data.get("html_url", ""),
        "name": data.get("name") or tag,
        "notes": data.get("body") or "",
    }


def check_for_update(current=None, fetch=None):
    """Return the release dict when it is newer than `current`, else None."""
    current = current or installed_version()
    release = fetch_latest_release(fetch=fetch)
    return release if is_newer(release["version"], current) else None


# --- applying ------------------------------------------------------------


@contextlib.contextmanager
def _update_lock(root):
    path = os.path.join(root, ".update.lock")
    try:
        handle = open(path, "a+", encoding="utf-8")
    except OSError as exc:
        raise UpdateError(f"cannot create the update lock: {exc}") from exc
    try:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:
            pass
        except OSError as exc:
            raise UpdateError("another update is already running") from exc
        yield
    finally:
        handle.close()


def _download(url, destination, fetch=None, timeout=60):
    fetch = fetch or _http_get
    try:
        payload = fetch(url, timeout)
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"download failed (HTTP {exc.code})") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpdateError(f"download failed: {exc}") from exc
    if not isinstance(payload, (bytes, bytearray)):
        raise UpdateError("download returned no binary payload")
    if len(payload) > MAX_TARBALL_BYTES:
        raise UpdateError("release archive is larger than the 50 MB limit")
    with open(destination, "wb") as handle:
        handle.write(payload)
    return destination


def _extract(archive_path, destination):
    root = os.path.realpath(destination)
    try:
        with tarfile.open(archive_path, "r:*") as archive:
            for member in archive.getmembers():
                target = os.path.realpath(os.path.join(destination, member.name))
                if target != root and not target.startswith(root + os.sep):
                    raise UpdateError("release archive escapes the temporary folder")
                if member.issym() or member.islnk():
                    raise UpdateError("release archive contains links")
            try:
                archive.extractall(destination, filter="data")
            except TypeError:  # Python < 3.12 has no extraction filters
                archive.extractall(destination)
    except (tarfile.TarError, OSError) as exc:
        raise UpdateError(f"cannot read the release archive: {exc}") from exc
    return destination


def _release_root(directory):
    candidates = [directory]
    try:
        for name in sorted(os.listdir(directory)):
            path = os.path.join(directory, name)
            if os.path.isdir(path):
                candidates.append(path)
    except OSError as exc:
        raise UpdateError(f"cannot inspect the release archive: {exc}") from exc
    for candidate in candidates:
        if os.path.isfile(os.path.join(candidate, "src", "main.py")) and os.path.isfile(
            os.path.join(candidate, "src", "version.py")
        ):
            return candidate
    raise UpdateError("release archive does not contain src/main.py")


def _replace_tree(source, root):
    """Copy the managed items into a staging dir, then swap them in."""
    items = [name for name in MANAGED_ITEMS if os.path.exists(os.path.join(source, name))]
    if "src" not in items:
        raise UpdateError("release archive is missing the src folder")

    stage = tempfile.mkdtemp(prefix=".clicktask-stage-", dir=root)
    new_dir = os.path.join(stage, "new")
    backup_dir = os.path.join(stage, "backup")
    os.makedirs(new_dir)
    os.makedirs(backup_dir)

    preexisting = {name: os.path.exists(os.path.join(root, name)) for name in items}
    try:
        for name in items:
            item_source = os.path.join(source, name)
            item_target = os.path.join(new_dir, name)
            if os.path.isdir(item_source):
                shutil.copytree(
                    item_source,
                    item_target,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )
            else:
                shutil.copy2(item_source, item_target)

        for name in items:
            current = os.path.join(root, name)
            if preexisting[name]:
                os.replace(current, os.path.join(backup_dir, name))
            os.replace(os.path.join(new_dir, name), current)
    except OSError as exc:
        for name in reversed(items):
            current = os.path.join(root, name)
            backup = os.path.join(backup_dir, name)
            if preexisting.get(name) and os.path.exists(backup):
                if os.path.isdir(current) and not os.path.islink(current):
                    shutil.rmtree(current, ignore_errors=True)
                elif os.path.exists(current):
                    _remove(current)
                os.replace(backup, current)
            elif not preexisting.get(name) and os.path.exists(current):
                _remove(current)
        shutil.rmtree(stage, ignore_errors=True)
        raise UpdateError(f"could not replace the installed files: {exc}") from exc

    shutil.rmtree(stage, ignore_errors=True)
    return items


def _remove(path):
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
    except OSError:
        pass


def _install_requirements(root, runner=None):
    """Reinstall Python deps when the release changed requirements.txt."""
    pip = os.path.join(root, ".venv", "bin", "pip")
    if not os.path.exists(pip):
        return False
    runner = runner or subprocess.run
    try:
        result = runner(
            [pip, "install", "--quiet", "-r", os.path.join(root, "requirements.txt")],
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise UpdateError(f"could not run pip: {exc}") from exc
    if getattr(result, "returncode", 0) != 0:
        detail = (getattr(result, "stderr", "") or "").strip().splitlines()
        raise UpdateError(
            "dependencies changed but pip failed: "
            + (detail[-1] if detail else "unknown error")
        )
    return True


def apply_release(release, root=None, fetch=None, force=False, pip_install=None):
    """Install `release` over an installed tree. Returns what happened."""
    root = os.path.abspath(root or installed_root())
    if not is_managed(root):
        raise UpdateError(
            f"{root} is not an installed build; run ./tools/install.sh first"
        )
    return _apply_locked(root, release, fetch, force, pip_install)


def _apply_locked(root, release, fetch, force, pip_install):
    with _update_lock(root):
        current = installed_version(root)
        remote = release.get("version") or str(release.get("tag", "")).lstrip("vV")
        if not force and not is_newer(remote, current):
            return {"updated": False, "from": current, "to": current}

        requirements_before = _read_text(os.path.join(root, "requirements.txt"))
        workdir = tempfile.mkdtemp(prefix="clicktask-update-")
        try:
            archive = _download(release["tarball_url"], os.path.join(workdir, "release.tar.gz"), fetch)
            source = _release_root(_extract(archive, os.path.join(workdir, "tree")))
            new_version = installer.read_version(source)
            if not force and not is_newer(new_version, current):
                return {"updated": False, "from": current, "to": current}
            _replace_tree(source, root)
            # Record the new version before touching pip: if a dependency
            # install fails, the tree is already the new release and the
            # marker/launcher must say so.
            marker = installer.read_marker(root)
            installer.write_marker(
                root,
                new_version,
                desktop=bool(marker.get("desktop", True)),
                autoupdate=bool(marker.get("autoupdate", True)),
            )
            installer.refresh(root, new_version)
            requirements_after = _read_text(os.path.join(root, "requirements.txt"))
            if requirements_before != requirements_after:
                _install_requirements(root, pip_install)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    return {"updated": True, "from": current, "to": new_version, "restart_required": True}


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


if __name__ == "__main__":
    try:
        latest = fetch_latest_release()
    except UpdateError as exc:
        print(f"clicktask: {exc}", file=sys.stderr)
        raise SystemExit(1)
    current = installed_version()
    if is_newer(latest["version"], current):
        print(f"{current} → {latest['version']} available")
    else:
        print(f"up to date ({current})")
