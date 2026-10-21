# ClickTask compared

TinyTask and GS Auto Clicker solve different problems, and Linux already has a
good answer for the first one:

| | TinyTask | GS Auto Clicker | **ClickTask** |
| :--- | :--- | :--- | :--- |
| Model | Record & replay mouse **and keyboard** | Timer-driven clicks | Timer-driven clicks |
| How you use it | Record once, replay the event stream | Configure interval/button, hit the hotkey | Same as GS, plus a CLI |
| Timing | Comes from the recording (speed, loop) | Fixed interval (h/m/s/**ms**) | Fixed interval, down to 1 ms |
| Keyboard | Records and replays it | Never touches it | Never touches it |
| Targeting | Wherever you clicked while recording | Cursor or pinned point, plus click sequences | Cursor, pinned point, or point sequence |
| Options | rec/play/speed/loop | Button, single/double, N clicks, hotkey | Button, single/double, hold, N clicks, hotkey |
| Platform | Windows | Windows | Linux, X11 |

If you want "replay what I did", use
[LinuxTask](https://github.com/JADRT22/LinuxTask). If you want "keep clicking
this spot at this rate", ClickTask is the tool.

**TinyTask** wins when the task needs keyboard events or a recording of a whole
session. **GS Auto Clicker** is closer in spirit, but is Windows-only and has no
CLI or point sequences. ClickTask adds a scriptable CLI, per-point timing and a
signature-verified self-update, at the cost of requiring X11.
