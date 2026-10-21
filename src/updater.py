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
import time
import urllib.error
import urllib.parse
import urllib.request

import installer
from version import REPOSITORY, VERSION

API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
API_TAG_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/tags/"
USER_AGENT = f"ClickTask/{VERSION} (+https://github.com/{REPOSITORY})"
TIMEOUT = 15
MAX_TARBALL_BYTES = 50 * 1024 * 1024
CACHE_MAX_AGE = 60 * 60  # one hour: repeated launches do not hit GitHub
PREVIOUS_DIR = ".previous"

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


def cache_path():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache"
    )
    return os.path.join(base, "clicktask", "update.json")


def read_cache(max_age=CACHE_MAX_AGE):
    """Return a release checked less than `max_age` seconds ago, or None."""
    try:
        with open(cache_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("version") or not data.get("tarball_url"):
        return None
    try:
        age = time.time() - float(data.get("checked_at", 0))
    except (TypeError, ValueError):
        return None
    if max_age is not None and age > max_age:
        return None
    return data


def write_cache(release):
    """Remember a release check so the next launch can skip the network."""
    payload = {
        "version": release["version"],
        "tag": release.get("tag", f"v{release['version']}"),
        "tarball_url": release["tarball_url"],
        "html_url": release.get("html_url", ""),
        "notes": release.get("notes", ""),
        "checked_at": time.time(),
    }
    path = cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(tmp, path)
        return path
    except OSError:
        return None


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


def _read_release(url, fetch, timeout, label):
    fetch = fetch or _http_get
    try:
        payload = fetch(url, timeout)
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"GitHub returned HTTP {exc.code} for {label}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpdateError(f"could not reach GitHub: {exc}") from exc
    try:
        data = json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else payload)
    except (UnicodeDecodeError, ValueError) as exc:
        raise UpdateError(f"GitHub sent an unexpected response: {exc}") from exc
    if not isinstance(data, dict) or not data.get("tag_name") or not data.get("tarball_url"):
        raise UpdateError(f"{label} has no tag or tarball")
    tag = str(data["tag_name"])
    return {
        "version": tag.lstrip("vV"),
        "tag": tag,
        "tarball_url": data["tarball_url"],
        "html_url": data.get("html_url", ""),
        "name": data.get("name") or tag,
        "notes": data.get("body") or "",
    }


def fetch_latest_release(fetch=None, timeout=TIMEOUT, use_cache=True, max_age=CACHE_MAX_AGE):
    """Return {version, tag, tarball_url, html_url, notes} for the latest release.

    A check younger than `max_age` is served from the cache, so reopening the
    app does not spend GitHub's unauthenticated rate limit. Pass
    `use_cache=False` for an explicit "check now".
    """
    if use_cache:
        cached = read_cache(max_age)
        if cached is not None:
            return dict(cached, cached=True)
    release = _read_release(API_URL, fetch, timeout, "the latest release")
    write_cache(release)
    return release


def fetch_release(tag, fetch=None, timeout=TIMEOUT):
    """Fetch one specific release by tag (used by `update --to`)."""
    tag = str(tag or "").strip()
    if not tag:
        raise UpdateError("a tag is required")
    url = API_TAG_URL + urllib.parse.quote(tag, safe="/")
    return _read_release(url, fetch, timeout, f"release {tag}")


def check_for_update(current=None, fetch=None, use_cache=True):
    """Return the release dict when it is newer than `current`, else None."""
    current = current or installed_version()
    release = fetch_latest_release(fetch=fetch, use_cache=use_cache)
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


def _replace_tree(source, root, keep_previous=True):
    """Copy the managed items into a staging dir, then swap them in.

    With `keep_previous` the replaced files are kept in `root/.previous` so a
    bad release can be rolled back without a download.
    """
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

    if keep_previous:
        try:
            previous = os.path.join(root, PREVIOUS_DIR)
            shutil.rmtree(previous, ignore_errors=True)
            os.replace(backup_dir, previous)
        except OSError:
            pass  # a missing backup must not turn a good update into a failure
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
            previous = os.path.join(root, PREVIOUS_DIR)
            if os.path.isdir(previous):
                _write_json(
                    os.path.join(previous, "manifest.json"),
                    {"version": current, "created_at": time.time()},
                )
            _remove(cache_path())
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


def _write_json(path, payload):
    try:
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(tmp, path)
    except OSError:
        pass


def rollback(root=None):
    """Restore the tree that the last update replaced. No network needed."""
    root = os.path.abspath(root or installed_root())
    if not is_managed(root):
        raise UpdateError(f"{root} is not an installed build; run ./tools/install.sh first")
    previous = os.path.join(root, PREVIOUS_DIR)
    if not os.path.isfile(os.path.join(previous, "src", "version.py")):
        raise UpdateError("there is no previous version to roll back to")

    with _update_lock(root):
        current = installed_version(root)
        manifest = _read_json(os.path.join(previous, "manifest.json"))
        target = manifest.get("version") or installer.read_version(previous)
        _replace_tree(previous, root, keep_previous=False)
        marker = installer.read_marker(root)
        installer.write_marker(
            root,
            target,
            desktop=bool(marker.get("desktop", True)),
            autoupdate=bool(marker.get("autoupdate", True)),
        )
        installer.refresh(root, target)
        shutil.rmtree(previous, ignore_errors=True)
        _remove(cache_path())

    return {"updated": True, "from": current, "to": target, "rollback": True}


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


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
