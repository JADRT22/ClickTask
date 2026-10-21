# Changelog

All notable changes to **ClickTask** will be documented in this file.

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
