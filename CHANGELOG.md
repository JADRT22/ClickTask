# Changelog

All notable changes to **ClickTask** will be documented in this file.

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
