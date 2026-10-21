# Contributing to ClickTask

Thanks for helping. This project is deliberately small: an interval clicker for
X11, with no keyboard automation and no Wayland backend. Patches that keep it
that way are the easiest to accept.

## Before you open a pull request

1. Run the suite: `python3 -m unittest discover -s tests -t .` — it must be
   green, and new behaviour needs a test (no display required; use
   `DryRunBackend` and a mocked `Display`).
2. Run a manual click test on a real X11 session:
   `./run.sh click --interval 500ms --count 3 --at 500,300`.
3. Keep the diff focused. Formatting-only or renaming churn is not accepted.

## Bug reports

Include:

- the exact command or the GUI steps;
- your desktop and session type (`echo $XDG_CURRENT_DESKTOP $XDG_SESSION_TYPE`);
- the output of the same run with `--dry-run` when the CLI is involved;
- whether the F6 grab succeeded (the status line says so).

## Code conventions

- Python 3.10+, standard library plus `python-xlib`; the GUI uses tkinter only.
- Every module keeps one responsibility: `engine` schedules, `backend` injects,
  `gui` builds plans and shows state.
- Comments explain *why*, not *what*. No attribution headers.
- Text and identifiers in English; commits in the imperative mood
  (`Add picker timeout`, not `Added...`).

## Scope guardrails

| Proposal | Status |
| --- | --- |
| New backends for Wayland (portal/uinput) | Discuss in an issue first — this is a design change |
| Keyboard automation or macro recording | Out of scope (LinuxTask) |
| Image detection, OCR, scheduled runs | Out of scope for v1 |
| Better picker UX, animations, themes | Welcome |
| Documentation and troubleshooting entries | Welcome |

## License

By contributing you agree that your work is released under the MIT license of
this repository.
