# ClickTask — v1 specification

## Goal

A Linux auto clicker modelled on **GS Auto Clicker**, not on TinyTask: the user
configures a rhythm and a target, presses a hotkey, and the tool clicks. Nothing
is recorded, and the keyboard is never touched — that is what
[LinuxTask](https://github.com/JADRT22/LinuxTask) already does.

Success for v1: on an X11 desktop (XFCE and other WMs) the user can start and
stop clicking with one key, control the interval down to 1 ms, choose button and
single/double clicks, cap the run at N clicks, pin clicks to a saved point, and
replay an ordered list of points in a loop — from the GUI or from a script.

## Scope

**In scope (v1)**

- Interval engine: h/m/s/ms fields, 1 ms floor, unlimited or N clicks.
- Click options: left/middle/right, single/double, optional hold per press.
- Position: current cursor or a fixed point captured from the pointer.
- Sequence mode: ordered points, per-point delay/button/double, loop count,
  optional total click cap.
- Global start/stop hotkey on X11 (default F6, configurable).
- Headless CLI with `--dry-run` for both modes.
- Settings persisted at `$XDG_CONFIG_HOME/clicktask/config.json`.
- User-level install with menu entry, desktop shortcut, icon and `clicktask`
  launcher (recognised by the desktop search bar).
- Self-update from GitHub releases, on startup and by a daily user timer, with
  the venv and settings preserved.

**Out of scope (v1)**

- Wayland input injection (XTEST does not reach Wayland clients).
- Keyboard automation and macro recording (LinuxTask's job).
- Image/colour detection triggers, scheduled runs, multiple simultaneous plans.
- Binary packaging (AppImage/Flatpak); the installer is source + venv.

## Architecture

| Module | Responsibility |
| --- | --- |
| `src/engine.py` | `ClickPlan`/`Point` data + `ClickEngine` worker thread. Interval scheduling with a monotonic clock; sequence playback; emits `start`/`click`/`stop`/`error` events. |
| `src/backend.py` | `X11Backend` (XTEST press/release, pointer warp, pointer query) and `DryRunBackend` (records actions). `BackendError` for anything the caller must report. |
| `src/hotkey.py` | `HotkeyListener`: `XGrabKey` on the root window with CapsLock/NumLock variants, own `Display` connection, auto-repeat filtered. |
| `src/config.py` | `DEFAULTS`, `normalize()` validation, atomic `load()`/`save()`. |
| `src/cli.py` | Argument parsing, interval/point/sequence-file parsing, plan building, exit codes. |
| `src/gui.py` | tkinter minimal window (big toggle button, counter, fade-in/pulse/pop animations) plus a Settings dialog holding the Clicker/Sequence tabs, hotkey field, click-to-pick flow, update toggle, plan building and config save on close. |
| `src/installer.py` | Launcher, menu/desktop entries, icon, systemd update timer, uninstall; all paths under `$HOME`. |
| `src/updater.py` | GitHub release lookup, tarball download, archive validation, atomic swap of managed folders, dependency refresh. |
| `src/version.py` | `VERSION` and `REPOSITORY`. |
| `src/main.py` | Route: no arguments → GUI, any argument → CLI. |

**Data flow.** GUI or CLI builds a `ClickPlan` → `ClickPlan.validate()` →
`ClickEngine.start()` → worker thread asks the backend to move and click →
events update the counter (GUI) or stdout (CLI). The engine never touches
tkinter, and the GUI never injects input itself.

**Timing.** The interval loop schedules against `time.monotonic()`; if the
system stalls and the next slot is already past, the next click happens
immediately and the schedule re-anchors, so a slow moment never produces a
burst of catch-up clicks.

**Threading.** One worker thread per run. `ClickEngine.stop()` joins it
(guarding against self-join). Hotkey callbacks arrive on the listener thread and
are marshalled into tkinter with `root.after`.

**Failure handling.** `BackendError` (no display, missing python-xlib, unknown
button) is reported to the user; a backend exception mid-run is emitted as an
`error` event and the run stops cleanly instead of taking the process down.
An unreadable or corrupt config falls back to defaults.

## CLI contract

```
clicktask click --interval 100ms --count 50 --button left [--double] [--hold MS] [--at X,Y] [--dry-run]
clicktask seq points.json --interval 100ms --loops 3 [--button left] [--count N] [--dry-run]
clicktask update [--check] [--force] [--quiet]
```

Exit codes: `0` success, `1` backend unavailable, `2` invalid arguments or plan,
`130` interrupted with Ctrl+C.

Sequence file: a JSON list of `{"x": int, "y": int, "delay_ms": int,
"button": "left|middle|right", "double": bool}` objects, or the same list under a
`points` key. A point delay of `0` inherits `--interval`.

## Testing

`python3 -m unittest discover -s tests -t .` — 110 tests. The engine, backend,
config, hotkey, CLI, installer and updater tests need no display, network or
systemd; the 11 GUI tests use a hidden window and are skipped when `DISPLAY` is
unset. Nothing moves your pointer:

- engine: counts, interval spacing, fixed vs cursor position, sequence order and
  loops, stop mid-run, backend error propagation, plan validation;
- backend: XTEST calls against a mocked `Display`, button codes, double-click
  pairs, hold, pointer query, dry-run recording;
- config: defaults, junk input, XDG paths, atomic save/load, corrupt file;
- hotkey: name parsing, grab/ungrab lock variants, auto-repeat filtering;
- CLI: interval/point/sequence parsing, plan building, dry-run runs, exit codes;
- point picking: grab success, returned coordinates, Escape cancel, timeout,
  grab failure, and the GUI applying/cancelling a pick;
- installer: launcher/menu/desktop entry contents, icon, timer units, refresh,
  uninstall and purge, all inside a temporary `$HOME`;
- updater: version comparison, GitHub payload validation, unsafe archive
  rejection, full apply from a fake tarball, dependency refresh, uninstall of
  removed modules, and the managed-install guard.

Real input injection is verified manually on an X11 session (see README).

## Decisions and risks

- **X11/XTEST over evdev/uinput** — no root, no `input` group, no device nodes;
  the trade-off is that Wayland is unsupported by design in v1.
- **No keyboard capture** — keeps the tool small and clearly complementary to
  LinuxTask.
- **1 ms floor is nominal** — the X server and the target app bound the real
  rate; very small intervals mean "as fast as the system allows".
- **Hotkey grab conflicts** — if another app owns F6, the grab fails; the GUI
  reports it and the CLI still works.
- **Updates are opt-out, not mandatory** — installed builds check GitHub on
  startup and daily; `--no-autoupdate`, the Settings toggle and
  `CLICKTASK_NO_UPDATE=1` can disable them. Tarballs are validated (layout,
  no links, no path escapes) before `os.replace` swaps the tree; failures roll
  back to the previous files.
- **Auto-update only for installed trees** — a marker file identifies installs,
  so a git checkout is never overwritten by mistake.
