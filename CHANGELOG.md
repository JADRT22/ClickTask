# Changelog

All notable changes to **ClickTask** will be documented in this file.

## [v1.2.0] - 2026-10-21

### Added
- **Update verification:** when a release publishes `SHA256SUMS`, the archive
  digest is checked before anything is extracted; a mismatch aborts the update
  and the old tree stays in place. Releases may also publish
  `SHA256SUMS.sig` (OpenSSH signature), which is verified against the key pinned
  in `src/release_key.py`, so a compromised GitHub account alone cannot push
  code. `tools/sign-release.sh` builds and uploads the archive, sums and
  signature.
- **Sequence management:** **↑ Up** / **↓ Down** reorder the selected point,
  **Duplicate** copies it below, and **Import…** / **Export…** read and write
  the same JSON the CLI uses.
- **Failsafe prompt:** starting a fixed-point or sequence run without a working
  hotkey now asks first, since the pointer leaves the Stop button.
- **Rate hint:** the interval panel explains that below ~5 ms the X server and
  the target app bound the real click rate.

### Changed
- CI matrix now covers Python **3.13** and **3.14** alongside 3.10 and 3.12.
- The TinyTask/GS comparison moved to `docs/COMPARISON.md`, keeping the README
  focused on install and usage.
- The suite is now 163 tests (160 headless, 3 gated input tests).

## [v1.1.5] - 2026-10-21

### Added
- **Single instance:** the GUI binds a Unix socket in
  `$XDG_RUNTIME_DIR/clicktask`. Launching ClickTask again asks the running
  window to come forward and exits, so two windows no longer fight over F6 and
  the pointer. Stale sockets from a crash are detected and replaced.
- **`clicktask doctor`:** read-only diagnostics for Python, tkinter,
  python-xlib, the X display, the hotkey and its keycode, install/managed state,
  launcher/menu/desktop shortcuts, the update timer, the cached release check
  and the settings path. Exit code 1 when a required check fails; warnings do
  not fail.

### Fixed
- The IPC listener compared `raise\n` against a stripped message and ignored
  every request; caught by the single-instance test.

## [v1.1.4] - 2026-10-21

### Fixed
- `clicktask update --to TAG` called the requested tag "latest" in its output;
  it now says "requested". No change to the update itself.

## [v1.1.3] - 2026-10-21

### Added
- **Update check cache:** the startup check reuses a result younger than one
  hour (`$XDG_CACHE_HOME/clicktask/update.json`), so reopening the app does not
  spend GitHub's unauthenticated rate limit. *Check now* and `clicktask update`
  always hit the network.
- **Rollback:** every update keeps the replaced tree in `.previous`;
  `clicktask update --rollback` restores it without downloading anything.
- **`clicktask update --to TAG`** installs a specific release, including an
  older one.

### Fixed
- **Failed hotkey rebind killed the old hotkey:** the listener was stopped
  before the new grab was attempted. The old key now stays active and the field
  reverts to it when the new name or grab fails.
- **Clear erased the sequence without asking:** the button now confirms first.

## [v1.1.2] - 2026-10-21

### Added
- **Editable sequence points:** *Edit…* (or double-click a row) opens a dialog
  for X, Y, delay, button, double-click and per-point hold. The table gained a
  *Hold ms* column.
- **Click cap for sequences:** *Max clicks* in the Sequence tab maps to the
  plan's `count`, so a list can stop after N clicks as well as after N loops.

### Fixed
- **Per-point `hold_ms` was lost on save:** `config._normalize_point` dropped
  the field, so a sequence reloaded without its holds. Existing configs keep
  working and now round-trip the value.
- **Sequence runs ignored the shared Hold field** as the default for points that
  do not set their own hold.
- **Dark theme covered checkbox/radio indicators and comboboxes:** on `clam`
  these are drawn from `indicatorbackground`, not `indicatorcolor`, so the edit
  dialog showed a light box. The dropdown list is themed too.

## [v1.1.1] - 2026-10-21

### Fixed
- **Startup update check could go silent.** The worker thread called
  `root.after()` directly, which on strict Tk builds (Python 3.14) fails with
  *main thread is not in main loop*; the exception was swallowed and the
  Settings label stayed on *checking…* forever. The result is now queued and
  polled from the main thread, like the point picker.
- Regression test for the manual/startup update path (GUI suite now 12 tests).

## [v1.1.0] - 2026-10-21

### Added
- **User-level installer** (`./install.sh`): copies ClickTask to
  `~/.local/share/clicktask`, creates the venv and registers the `clicktask`
  launcher, an application-menu entry (found by the desktop search bar), a
  desktop shortcut, the app icon and a daily systemd user timer. Options:
  `--prefix DIR`, `--no-desktop`, `--no-autoupdate`.
- **Self-update** (`clicktask update`): checks the latest GitHub release,
  downloads its tarball, rejects unsafe archives and links, swaps `src/`,
  `tools/`, `docs/` and `assets/` only after the download is verified, reinstalls
  dependencies when `requirements.txt` changes and refreshes the shortcuts. The
  GUI checks once on startup, with a Settings toggle; the timer runs
  `update --quiet` every day. Git checkouts are never modified.
- **Settings:** auto-update checkbox, installed version and a *Check now* button.
- **App icon** (SVG + 64 px PNG) used by the menu entry, the desktop shortcut and
  the window.
- **Installer/updater tests**, all inside a temporary `$HOME`; the suite is now
  110 tests.

### Changed
- `VERSION` moved to `src/version.py`, the single source of truth for the CLI,
  installer and updater.
- `tools/uninstall.sh` now removes the launcher, menu and desktop entries, icon
  and update timer, not only the venv.

### Notes
- The updater is the only code that opens a socket, and only towards
  `api.github.com` / GitHub release assets. Disable it in Settings or with
  `./install.sh --no-autoupdate`.
- X11 only, unchanged: `XTEST` does not reach Wayland clients.

## [v1.0.0] - 2026-10-20

### Added
- **Interval clicker (GS Auto Clicker model):** click at a fixed rhythm with
  h/m/s/ms fields, down to 1 ms, unlimited or capped at N clicks.
- **Click options:** left, middle or right button, single or double click, and an
  optional hold per press.
- **Targeting:** follow the current cursor or pin clicks to a saved X,Y point.
- **Click-to-pick points:** press *Pick on screen* and the next click you make
  becomes the coordinate — the click is grabbed and never reaches the app
  behind it. Esc cancels.
- **Click sequences:** ordered points with per-point delay, button and
  double-click flags, looped a set number of times or forever.
- **Global hotkey:** F6 by default, configurable through the GUI.
- **Headless CLI:** `click` and `seq` commands with `--dry-run`, usable from
  scripts and window-manager keybinds.
- **Persistent settings:** stored in `~/.config/clicktask/config.json` and
  reloaded on start.
- **Compact GUI:** one big toggle button on a small dark card, options behind a
  Settings dialog, with a fade-in, a pulse while clicking and a counter that
  pops on each click. The dark theme covers every panel (tabs, tables, entries,
  spin boxes, labels), not just the buttons.
- **GUI and engine split:** tkinter front-end, worker-thread engine, XTEST
  backend, covered by 80 tests (11 of them GUI tests, skipped without a display).

### Notes
- X11 only: `XTEST` does not reach Wayland clients. Keyboard automation is
  intentionally out of scope — that is LinuxTask's job.
