# Roadmap and design decisions

This page records what was adopted from the outside review of v1.1.x, what was
deliberately deferred, and why. It is a decision log, not a promise list.

## Adopted

| Item | What shipped |
| --- | --- |
| **Verified updates** | `SHA256SUMS` is checked before extraction; `SHA256SUMS.sig` (OpenSSH) is verified against `src/release_key.py` when present. `tools/sign-release.sh` builds and uploads the assets. |
| **Failsafe** | A fixed-point or sequence run started without a working hotkey asks for confirmation first, because the pointer leaves the Stop button. The interval panel states that below ~5 ms the machine, not the setting, decides the rate. |
| **CI coverage** | The matrix runs 3.10, 3.12, 3.13 and 3.14, plus the Xvfb job that exercises the GUI and a real XTEST click. |
| **Release hygiene** | Changes are grouped by theme and the changelog is written per release; no release is cut just to reword one line. |
| **README focus** | The TinyTask/GS comparison moved to [COMPARISON.md](COMPARISON.md); install and usage stay in the README. |
| **Everything on one window** | v1.0–1.2 hid all options behind a Settings dialog; the reviewer question "why is configuring a clicker a detour?" won: v1.3.0 puts plan, interval, options, repeat, position and the sequence panel straight on the main window (OP Auto Clicker layout), with Start/Stop buttons and a footer row. |
| **Discoverability** | Repository topics cover the stack and the use case. A demo GIF is still missing: it needs a real screen recording, not a generated image. |

## Deferred

### Wayland backend

Large, and the architecture changes: `XTEST` cannot reach native Wayland
clients. The realistic paths are the `RemoteDesktop` portal (user consent per
session, portal-specific coordinate space) or a `uinput` helper (needs the
`input` group and device access). Either one is a separate backend behind the
same `Backend` interface, with its own tests and permission story. Doing it
halfway — an XWayland-only build that silently misses native windows — would be
worse than the current explicit "X11 only".

### Distribution packages

An AUR `PKGBUILD`, `pipx` packaging or an AppImage would each need their own
release pipeline and a promise to keep them working. The user-level installer
already covers the "no sudo, menu entry, self-update" case. Revisit after the
Wayland question, because packaging a moving target twice is wasted effort.

### Release channels

A `beta` channel and opt-in auto-update sound attractive, but with a single
maintainer the practical fix is fewer, better-tested releases (adopted above).
A channel without users testing it just adds a second code path to keep alive.

### Signing by default

The updater can verify signatures today, but the key must exist first. The
project's public key is intentionally not generated on the user's behalf: the
private half is a credential, and creating credentials without consent is not a
setup step an installer should take. Until `SIGNER_PUBLIC_KEY` is filled in
`src/release_key.py`, releases carry checksums only, which catches corruption
but not a rewritten release.

## Non-goals

- Keyboard capture and macro recording (that is LinuxTask's job).
- Multiple simultaneous plans, scheduled runs, image/colour triggers.
- Privileged helpers or device nodes for input.
