# -*- coding: utf-8 -*-
"""
ClickTask - gui.py
Description: Single-window tkinter front-end in the OP Auto Clicker style:
             every option is visible in grouped sections (interval, click
             options, repeat, cursor position), with Start/Stop buttons, an
             expandable sequence panel and a click-anywhere point picker.
             Subtle animations (fade-in, pulsing Stop while running, counter
             pop) and click-anywhere point picking are kept. Input injection
             always goes through the engine; the GUI only builds plans and
             shows state.
Author: JADRT22 (https://github.com/JADRT22)
License: MIT
"""

import json
import os
import queue
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk

import backend
import config
import engine
import hotkey
import singleinstance
from version import VERSION

APP_TITLE = "ClickTask"

# Palette: a quiet dark card with one accent; the Stop button turns red while
# clicking, like the old toggle button.
BG = "#1d2129"
BG_SOFT = "#252b35"
FG = "#e7eaf0"
MUTED = "#98a1b0"
ACCENT = "#3f8cff"
ACCENT_DARK = "#16233a"
RUNNING = "#e0533d"
BORDER = "#39404d"
FIELD = "#161a21"
FIELD_SOFT = "#20262f"

PICK_TIMEOUT = 60


class ClickTaskApp:
    """Single window holding every option plus the running controls."""

    def __init__(self, root, settings=None):
        self.root = root
        self.settings = config.normalize(settings or config.load())
        self.points = [engine.Point(**point) for point in self.settings["points"]]
        self.hotkey_listener = None
        self.engine = None
        self._after_ids = {}
        self._pick_active = False
        self._pick_target = "position"
        self._pick_queue = None
        self._pick_toast = None
        self._toast_label = None
        self._toast_message = ""
        self._last_count = -1
        self._update_running = False
        self._update_manual = False
        self._update_queue = queue.Queue()
        self._raise_queue = queue.Queue()

        root.title(APP_TITLE)
        root.configure(bg=BG)
        root.resizable(False, False)
        self._set_window_icon()

        self._build_vars()
        self._setup_style()
        self._build_main()
        self._start_hotkey()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        # Tk keeps scheduling animations and polls; cancel them on any destroy
        # (window manager, tests, or a hard close) so no callback fires late.
        root.bind("<Destroy>", self._on_destroy, add="+")
        self._fade_in()
        # Window managers often ignore a pre-map geometry request; nudge it once
        # the window is actually on screen so it lands centred.
        self._schedule("center", 80, lambda: self._center(self.root))
        self._auto_update_startup()

    # --- construction ---

    def _set_window_icon(self):
        """Use the same icon as the menu entry, when the asset is around."""
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "assets",
            "clicktask.png",
        )
        if not os.path.exists(path):
            return
        try:
            self._icon = tk.PhotoImage(file=path)
            self.root.iconphoto(True, self._icon)
        except tk.TclError:
            pass

    def _build_vars(self):
        interval = int(self.settings["interval_ms"])
        self.var_hours = tk.StringVar(value=str(interval // 3600000))
        self.var_minutes = tk.StringVar(value=str(interval % 3600000 // 60000))
        self.var_seconds = tk.StringVar(value=str(interval % 60000 // 1000))
        self.var_millis = tk.StringVar(value=str(interval % 1000))
        self.var_offset = tk.StringVar(value=str(self.settings.get("random_offset_ms", 0)))

        self.var_button = tk.StringVar(value=self.settings["button"])
        self.var_double = tk.BooleanVar(value=bool(self.settings["double"]))
        self.var_hold = tk.StringVar(value=str(self.settings["hold_ms"]))
        self.var_unlimited = tk.BooleanVar(value=int(self.settings["count"]) == 0)
        self.var_count = tk.StringVar(value=str(max(1, int(self.settings["count"]))))
        self.var_fixed = tk.BooleanVar(value=bool(self.settings["use_fixed_position"]))
        position = self.settings["position"] or [0, 0]
        self.var_x = tk.StringVar(value=str(position[0]))
        self.var_y = tk.StringVar(value=str(position[1]))
        self.var_loops = tk.StringVar(value=str(self.settings["sequence_loops"]))
        self.var_seq_count = tk.StringVar(value=str(self.settings["sequence_count"]))
        self.var_hotkey = tk.StringVar(value=self.settings["hotkey"])
        self.var_status = tk.StringVar(value="Idle")
        self.var_counter = tk.StringVar(value="0 clicks")
        self.var_start_label = tk.StringVar()
        self.var_stop_label = tk.StringVar()
        self.var_mode = tk.StringVar(value="clicker")
        self.var_seq_list = tk.BooleanVar(value=False)
        self.var_auto_update = tk.BooleanVar(value=bool(self.settings["auto_update"]))
        self.var_update = tk.StringVar(value=f"v{VERSION}")

    def _font(self, size, weight="normal"):
        family = tkfont.nametofont("TkDefaultFont").cget("family")
        return (family, size, weight)

    def _setup_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")  # the only bundled theme that honours colours
        except tk.TclError:
            pass

        # Paint every widget family: setting only the frames and buttons leaves
        # tree views and text fields with the light defaults.
        style.configure(
            ".",
            background=BG,
            foreground=FG,
            fieldbackground=FIELD,
            bordercolor=BORDER,
            lightcolor=BG_SOFT,
            darkcolor=BG,
            troughcolor=FIELD,
            focuscolor=ACCENT,
            insertcolor=FG,
            selectbackground=ACCENT,
            selectforeground="#ffffff",
            font=self._font(10),
        )
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("TSeparator", background=BORDER)
        style.configure("TLabelframe", background=BG, bordercolor=BORDER, relief="solid")
        style.configure("TLabelframe.Label", background=BG, foreground=MUTED,
                        font=self._font(9, "bold"))

        style.configure("Treeview", background=FIELD, fieldbackground=FIELD,
                        foreground=FG, borderwidth=0, rowheight=22)
        style.configure("Treeview.Heading", background=BG_SOFT, foreground=FG,
                        borderwidth=0, font=self._font(9, "bold"), relief="flat")
        style.map("Treeview.Heading", background=[("active", FIELD_SOFT)])
        style.map("Treeview",
                  background=[("selected", ACCENT)],
                  foreground=[("selected", "#ffffff")])

        style.configure("TEntry", fieldbackground=FIELD_SOFT, foreground=FG,
                        bordercolor=BORDER, insertcolor=FG, padding=3)
        style.configure("TSpinbox", fieldbackground=FIELD_SOFT, background=BG_SOFT,
                        foreground=FG, arrowcolor=FG, bordercolor=BORDER, padding=2)
        style.configure("TCombobox", fieldbackground=FIELD_SOFT, background=BG_SOFT,
                        foreground=FG, arrowcolor=FG, bordercolor=BORDER, padding=2,
                        selectbackground=ACCENT, selectforeground="#ffffff")
        style.map("TCombobox",
                  fieldbackground=[("readonly", FIELD_SOFT), ("disabled", BG_SOFT)],
                  foreground=[("readonly", FG), ("disabled", MUTED)],
                  background=[("active", BG_SOFT)])
        # The dropdown list is a classic Tk listbox, not a ttk style.
        self.root.option_add("*TCombobox*Listbox.background", FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        # clam draws the indicator from `indicatorbackground`; the other themes
        # use `indicatorcolor`. Set both, or the box stays white on clam.
        style.configure("TRadiobutton", background=BG, foreground=FG,
                        indicatorcolor=FIELD_SOFT, indicatorbackground=FIELD_SOFT,
                        indicatorforeground=ACCENT)
        style.map("TRadiobutton", background=[("active", BG)],
                  indicatorcolor=[("selected", ACCENT)],
                  indicatorbackground=[("selected", FIELD_SOFT)],
                  indicatorforeground=[("selected", "#ffffff")])
        style.configure("TCheckbutton", background=BG, foreground=FG,
                        indicatorcolor=FIELD_SOFT, indicatorbackground=FIELD_SOFT,
                        indicatorforeground=ACCENT)
        style.map("TCheckbutton", background=[("active", BG)],
                  indicatorcolor=[("selected", ACCENT)],
                  indicatorbackground=[("selected", FIELD_SOFT)],
                  indicatorforeground=[("selected", "#ffffff")])
        style.configure("TScrollbar", background=BG_SOFT, troughcolor=FIELD,
                        bordercolor=BORDER, arrowcolor=MUTED)

        style.configure("Card.TFrame", background=BG)
        style.configure("Counter.TLabel", background=BG, foreground=FG, font=self._font(18, "bold"))
        style.configure("Status.TLabel", background=BG, foreground=MUTED, font=self._font(9))
        # Start keeps the accent look; Stop is neutral grey until it is needed.
        style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                        font=self._font(12, "bold"), padding=(10, 16), borderwidth=0,
                        focusthickness=0)
        style.configure("Stop.TButton", background=BG_SOFT, foreground=FG,
                        font=self._font(12, "bold"), padding=(10, 16), borderwidth=0,
                        focusthickness=0)
        style.configure("Running.TButton", background=RUNNING, foreground="#ffffff",
                        font=self._font(12, "bold"), padding=(10, 16), borderwidth=0,
                        focusthickness=0)
        style.configure("RunningAlt.TButton", background="#f0674f", foreground="#ffffff",
                        font=self._font(12, "bold"), padding=(10, 16), borderwidth=0,
                        focusthickness=0)
        style.configure("Ghost.TButton", background=BG_SOFT, foreground=FG,
                        font=self._font(10), padding=(6, 6), borderwidth=0)
        style.map("Ghost.TButton", background=[("active", "#313846")])
        style.map("Accent.TButton",
                  background=[("active", "#5c9dff"), ("pressed", ACCENT),
                              ("disabled", ACCENT_DARK)],
                  foreground=[("disabled", MUTED)])
        style.map("Stop.TButton",
                  background=[("active", "#313846"), ("disabled", BG_SOFT)],
                  foreground=[("disabled", MUTED)])
        style.map("Running.TButton", background=[("active", "#f0674f"), ("pressed", RUNNING)])
        style.map("RunningAlt.TButton", background=[("active", RUNNING)])

    def _build_main(self):
        frame = ttk.Frame(self.root, style="Card.TFrame", padding=12)
        frame.pack(fill="both", expand=True)

        # Plan selector: which section Start runs.
        plan_row = ttk.Frame(frame, style="Card.TFrame")
        plan_row.pack(fill="x")
        ttk.Label(plan_row, text="Click plan:", style="Status.TLabel").pack(side="left")
        ttk.Radiobutton(plan_row, text="Clicker", value="clicker",
                        variable=self.var_mode).pack(side="left", padx=(6, 0))
        ttk.Radiobutton(plan_row, text="Sequence", value="sequence",
                        variable=self.var_mode).pack(side="left", padx=(8, 0))
        self.counter_label = ttk.Label(plan_row, textvariable=self.var_counter,
                                       style="Counter.TLabel", anchor="e")
        self.counter_label.pack(side="right")

        self._build_clicker_group(frame)
        self._build_sequence_group(frame)

        exec_row = ttk.Frame(frame, style="Card.TFrame")
        exec_row.pack(fill="x", pady=(10, 0))
        self.button_start = ttk.Button(
            exec_row, textvariable=self.var_start_label, command=self.start,
            style="Accent.TButton",
        )
        self.button_start.pack(side="left", fill="x", expand=True)
        self.button_stop = ttk.Button(
            exec_row, textvariable=self.var_stop_label, command=self.stop,
            style="Stop.TButton", state="disabled",
        )
        self.button_stop.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self._set_exec_labels(False)

        ttk.Label(frame, textvariable=self.var_status, style="Status.TLabel",
                  wraplength=640, justify="center").pack(fill="x", pady=(8, 0))

        self._build_footer(frame)
        self._center(self.root)

    def _build_clicker_group(self, frame):
        interval = ttk.LabelFrame(frame, text="Click interval", padding=8)
        interval.pack(fill="x", pady=(8, 0))
        for label, var, limit in (
            ("h", self.var_hours, 23),
            ("m", self.var_minutes, 59),
            ("s", self.var_seconds, 59),
            ("ms", self.var_millis, 999),
        ):
            column = ttk.Frame(interval)
            column.pack(side="left", padx=(0, 8))
            ttk.Spinbox(column, from_=0, to=limit, width=5, textvariable=var).pack(side="left")
            ttk.Label(column, text=label).pack(side="left", padx=(2, 0))
        jitter = ttk.Frame(interval)
        jitter.pack(side="left", padx=(8, 0))
        ttk.Label(jitter, text="Jitter ±", style="Status.TLabel").pack(side="left")
        ttk.Spinbox(jitter, from_=0, to=10000, width=5,
                    textvariable=self.var_offset).pack(side="left", padx=(2, 2))
        ttk.Label(jitter, text="ms", style="Status.TLabel").pack(side="left")
        ttk.Label(
            interval,
            text="Below ~5 ms the X server and the target app bound the real rate.",
            style="Status.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        click = ttk.LabelFrame(frame, text="Click options", padding=8)
        click.pack(fill="x", pady=(8, 0))
        row = ttk.Frame(click)
        row.pack(anchor="w")
        ttk.Label(row, text="Mouse button:", style="Status.TLabel").pack(side="left")
        for value, label in (("left", "Left"), ("middle", "Middle"), ("right", "Right")):
            ttk.Radiobutton(row, text=label, value=value,
                            variable=self.var_button).pack(side="left", padx=(4, 0))
        row2 = ttk.Frame(click)
        row2.pack(anchor="w", pady=(6, 0))
        ttk.Label(row2, text="Click type:", style="Status.TLabel").pack(side="left")
        ttk.Radiobutton(row2, text="Single", value=False,
                        variable=self.var_double).pack(side="left", padx=(4, 0))
        ttk.Radiobutton(row2, text="Double", value=True,
                        variable=self.var_double).pack(side="left", padx=(8, 0))
        ttk.Label(row2, text="Hold (ms):", style="Status.TLabel").pack(side="left", padx=(12, 4))
        ttk.Entry(row2, textvariable=self.var_hold, width=7).pack(side="left")

        repeat = ttk.LabelFrame(frame, text="Click repeat", padding=8)
        repeat.pack(fill="x", pady=(8, 0))
        row3 = ttk.Frame(repeat)
        row3.pack(anchor="w")
        ttk.Radiobutton(row3, text="Repeat until stopped", value=True,
                        variable=self.var_unlimited).pack(side="left")
        ttk.Radiobutton(row3, text="Repeat", value=False,
                        variable=self.var_unlimited).pack(side="left", padx=(14, 0))
        ttk.Entry(row3, textvariable=self.var_count, width=7).pack(side="left", padx=4)
        ttk.Label(row3, text="times", style="Status.TLabel").pack(side="left")

        position = ttk.LabelFrame(frame, text="Cursor position", padding=8)
        position.pack(fill="x", pady=(8, 0))
        row4 = ttk.Frame(position)
        row4.pack(anchor="w")
        ttk.Radiobutton(row4, text="Current location", value=False,
                        variable=self.var_fixed).pack(side="left")
        ttk.Radiobutton(row4, text="Fixed point", value=True,
                        variable=self.var_fixed).pack(side="left", padx=(14, 0))
        ttk.Label(row4, text="X", style="Status.TLabel").pack(side="left", padx=(10, 2))
        ttk.Entry(row4, textvariable=self.var_x, width=6).pack(side="left")
        ttk.Label(row4, text="Y", style="Status.TLabel").pack(side="left", padx=(6, 2))
        ttk.Entry(row4, textvariable=self.var_y, width=6).pack(side="left")
        ttk.Button(row4, text="Pick on screen", command=lambda: self._start_pick("position"),
                   style="Ghost.TButton").pack(side="left", padx=8)

    def _build_sequence_group(self, frame):
        sequence = ttk.LabelFrame(frame, text="Sequence", padding=8)
        sequence.pack(fill="x", pady=(8, 0))

        header = ttk.Frame(sequence)
        header.pack(fill="x")
        for text, command in (
            ("Pick…", lambda: self._start_pick("sequence")),
            ("Edit…", self.edit_point),
            ("Remove", self.remove_point),
            ("Clear", self.clear_points),
            ("↑", lambda: self.move_point(-1)),
            ("↓", lambda: self.move_point(1)),
            ("Duplicate", self.duplicate_point),
            ("Import…", self.import_points),
            ("Export…", self.export_points),
        ):
            ttk.Button(header, text=text, command=command,
                       style="Ghost.TButton").pack(side="left", padx=(0, 5))
        ttk.Checkbutton(header, text="Show list", variable=self.var_seq_list,
                        command=self.toggle_sequence_list).pack(side="right")

        self.sequence_body = ttk.Frame(sequence)
        if self.var_seq_list.get():
            self.sequence_body.pack(fill="both", pady=(6, 0))
        self.tree = ttk.Treeview(
            self.sequence_body,
            columns=("x", "y", "delay", "button", "double", "hold"),
            show="headings",
            height=6,
        )
        for column, label, width in (
            ("x", "X", 46),
            ("y", "Y", 46),
            ("delay", "Delay ms", 66),
            ("button", "Button", 62),
            ("double", "Double", 58),
            ("hold", "Hold ms", 60),
        ):
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, anchor="center")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda event: self.edit_point())
        self._refresh_points()

        loops = ttk.Frame(self.sequence_body)
        loops.pack(fill="x", pady=(6, 0))
        ttk.Label(loops, text="Loops:", style="Status.TLabel").pack(side="left")
        ttk.Entry(loops, textvariable=self.var_loops, width=6).pack(side="left", padx=6)
        ttk.Label(loops, text="Max clicks:", style="Status.TLabel").pack(side="left", padx=(10, 4))
        ttk.Entry(loops, textvariable=self.var_seq_count, width=7).pack(side="left")
        ttk.Label(loops, text="0 = unlimited", style="Status.TLabel").pack(side="left", padx=8)

    def _build_footer(self, frame):
        footer = ttk.Frame(frame, style="Card.TFrame")
        footer.pack(fill="x", pady=(8, 0))
        ttk.Label(footer, text="Toggle hotkey:", style="Status.TLabel").pack(side="left")
        ttk.Entry(footer, textvariable=self.var_hotkey, width=8).pack(side="left", padx=6)
        ttk.Button(footer, text="Apply", command=self._start_hotkey,
                   style="Ghost.TButton").pack(side="left")
        ttk.Checkbutton(footer, text="Auto-update", variable=self.var_auto_update
                        ).pack(side="left", padx=(14, 0))
        ttk.Button(footer, text="Check updates", command=lambda: self.check_updates(True),
                   style="Ghost.TButton").pack(side="left", padx=6)
        ttk.Label(footer, textvariable=self.var_update, style="Status.TLabel").pack(
            side="right")

    def toggle_sequence_list(self):
        if self.var_seq_list.get():
            self.sequence_body.pack(fill="both", pady=(6, 0))
        else:
            self.sequence_body.pack_forget()

    @staticmethod
    def _center(window):
        window.update_idletasks()
        width = window.winfo_width()
        height = window.winfo_height()
        x = (window.winfo_screenwidth() - width) // 2
        y = (window.winfo_screenheight() - height) // 3
        window.geometry(f"+{x}+{y}")

    def _target_text(self, position=None):
        """One line describing where a run will click (for the status line)."""
        if position is None:
            try:
                position = self.position()
            except ValueError:
                position = None
        if position is None:
            return "clicks at the cursor"
        return f"clicks at {position[0]}, {position[1]} (fixed point)"

    def _set_exec_labels(self, running):
        key = (self.var_hotkey.get() if hasattr(self, "var_hotkey") else "F6").strip().upper()
        self.var_start_label.set(f"Start  ({key})")
        self.var_stop_label.set(f"Stop  ({key})")

    # --- single instance -------------------------------------------------

    def request_focus(self):
        """Called from the IPC thread: hand the request to the Tk thread."""
        self._raise_queue.put(True)

    def start_ipc_poll(self):
        self._schedule("ipc", 200, self._poll_ipc)

    def _poll_ipc(self):
        raised = False
        while True:
            try:
                self._raise_queue.get_nowait()
            except queue.Empty:
                break
            raised = True
        if raised:
            self.focus_window()
        self._schedule("ipc", 250, self._poll_ipc)

    def focus_window(self):
        """Bring the existing window forward when a second launch happens."""
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(150, self._drop_topmost)
            self.root.focus_force()
        except tk.TclError:
            pass

    def _drop_topmost(self):
        try:
            self.root.attributes("-topmost", False)
        except tk.TclError:
            pass

    # --- animations ---

    def _on_destroy(self, event):
        if event.widget is self.root:
            self._cleanup_after_ids()

    def _cleanup_after_ids(self):
        for key in list(self._after_ids):
            self._unset(key)

    def _schedule(self, key, delay, callback):
        self._unset(key)
        self._after_ids[key] = self.root.after(delay, callback)

    def _unset(self, key):
        after_id = self._after_ids.pop(key, None)
        if after_id is not None:
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass

    def _fade_in(self, step=0):
        """Soft appear; silently skipped when the X server has no compositor."""
        try:
            self.root.attributes("-alpha", min(1.0, 0.25 + step * 0.15))
        except tk.TclError:
            return
        if step < 5:
            self._schedule("fade", 18, lambda: self._fade_in(step + 1))

    def _pulse(self, bright=False):
        """Breathe between two shades of red while clicking."""
        if self.engine is None or not self.engine.running:
            return
        self.button_stop.configure(style="RunningAlt.TButton" if bright else "Running.TButton")
        self._schedule("pulse", 620, lambda: self._pulse(not bright))

    def _pop_counter(self):
        style = ttk.Style(self.root)
        style.configure("Counter.TLabel", font=self._font(21, "bold"))
        self._schedule("pop", 130, self._reset_counter_style)

    def _reset_counter_style(self):
        ttk.Style(self.root).configure("Counter.TLabel", font=self._font(18, "bold"))

    def _blink_toast(self, step=0):
        if self._toast_label is None:
            return
        self._toast_label.configure(text=self._toast_message + "." * (step % 4))
        self._schedule("toast", 340, lambda: self._blink_toast(step + 1))

    # --- pick flow ---

    def _show_pick_toast(self, message):
        self._hide_pick_toast()
        toast = tk.Toplevel(self.root)
        toast.overrideredirect(True)
        try:
            toast.attributes("-topmost", True)
        except tk.TclError:
            pass
        toast.configure(bg=ACCENT_DARK)
        frame = tk.Frame(toast, bg=ACCENT_DARK, padx=18, pady=12)
        frame.pack()
        self._toast_label = tk.Label(
            frame, text=message, bg=ACCENT_DARK, fg=FG, font=self._font(11, "bold")
        )
        self._toast_label.pack()
        toast.update_idletasks()
        width = toast.winfo_reqwidth()
        x = (toast.winfo_screenwidth() - width) // 2
        toast.geometry(f"+{x}+70")
        self._pick_toast = toast
        self._toast_message = message
        self._blink_toast(0)

    def _hide_pick_toast(self):
        self._unset("toast")
        if self._pick_toast is not None:
            try:
                self._pick_toast.destroy()
            except tk.TclError:
                pass
        self._pick_toast = None
        self._toast_label = None

    def _start_pick(self, target):
        """Ask the user to click the screen; that click becomes the point."""
        if self._pick_active:
            return
        self._pick_active = True
        self._pick_target = target
        self._pick_queue = queue.Queue()
        message = (
            "Click the next point of the sequence — Esc cancels"
            if target == "sequence"
            else "Click the point to click — Esc cancels"
        )
        self._show_pick_toast(message)
        self.var_status.set("Waiting for your click…")
        threading.Thread(target=self._pick_worker, daemon=True).start()
        self._schedule("pick", 80, self._poll_pick)

    def _pick_worker(self):
        try:
            point = backend.capture_click(timeout=PICK_TIMEOUT)
            self._pick_queue.put((point, None))
        except backend.BackendError as exc:
            self._pick_queue.put((None, exc))

    def _poll_pick(self):
        try:
            point, error = self._pick_queue.get_nowait()
        except queue.Empty:
            self._schedule("pick", 80, self._poll_pick)
            return
        self._finish_pick(point, error)

    def _finish_pick(self, point, error):
        self._pick_active = False
        self._hide_pick_toast()
        if error is not None:
            self.var_status.set("Pick failed")
            messagebox.showerror(APP_TITLE, str(error))
            return
        if point is None:
            self.var_status.set("Pick cancelled")
            return
        x, y = point
        if self._pick_target == "sequence":
            self.points.append(
                engine.Point(
                    x=x,
                    y=y,
                    delay_ms=self.interval_ms(),
                    button=self.var_button.get(),
                    double=self.var_double.get(),
                )
            )
            self._refresh_points()
            self.var_status.set(f"Point added at {x},{y}")
        else:
            self.var_x.set(str(x))
            self.var_y.set(str(y))
            self.var_fixed.set(True)
            self.var_status.set(f"Fixed point set to {x},{y}")

    # --- helpers ---

    def _read_int(self, var, default=0, minimum=0):
        try:
            value = int(str(var.get()).strip())
        except (TypeError, ValueError):
            return default
        return max(minimum, value)

    def interval_ms(self):
        hours = self._read_int(self.var_hours)
        minutes = self._read_int(self.var_minutes)
        seconds = self._read_int(self.var_seconds)
        millis = self._read_int(self.var_millis)
        total = ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis
        return max(1, total)

    def position(self):
        if not self.var_fixed.get():
            return None
        return (self._read_int(self.var_x), self._read_int(self.var_y))

    def remove_point(self):
        selection = self.tree.selection()
        if not selection:
            return
        index = self.tree.index(selection[0])
        if 0 <= index < len(self.points):
            self.points.pop(index)
            self._refresh_points()

    def _selected_index(self):
        selection = self.tree.selection()
        if not selection:
            return None
        index = self.tree.index(selection[0])
        return index if 0 <= index < len(self.points) else None

    def move_point(self, offset):
        """Move the selected point up (-1) or down (+1)."""
        index = self._selected_index()
        if index is None:
            self.var_status.set("Select a point first")
            return False
        target = index + offset
        if not 0 <= target < len(self.points):
            return False
        self.points[index], self.points[target] = self.points[target], self.points[index]
        self._refresh_points()
        children = self.tree.get_children()
        self.tree.selection_set(children[target])
        self.tree.see(children[target])
        self.var_status.set(f"Moved point {index + 1} to {target + 1}")
        return True

    def duplicate_point(self):
        index = self._selected_index()
        if index is None:
            self.var_status.set("Select a point to duplicate")
            return False
        original = self.points[index]
        clone = engine.Point(
            x=original.x,
            y=original.y,
            delay_ms=original.delay_ms,
            button=original.button,
            double=original.double,
            hold_ms=original.hold_ms,
        )
        self.points.insert(index + 1, clone)
        self._refresh_points()
        children = self.tree.get_children()
        self.tree.selection_set(children[index + 1])
        self.tree.see(children[index + 1])
        self.var_status.set(f"Duplicated point {index + 1}")
        return True

    def _points_payload(self):
        return [
            {
                "x": point.x,
                "y": point.y,
                "delay_ms": point.delay_ms,
                "button": point.button,
                "double": point.double,
                "hold_ms": point.hold_ms,
            }
            for point in self.points
        ]

    def export_points(self, path=None):
        """Save the sequence as the same JSON format the CLI reads."""
        if not self.points:
            self.var_status.set("Nothing to export")
            return False
        if path is None:
            from tkinter import filedialog

            path = filedialog.asksaveasfilename(
                parent=self.root,
                title="Export sequence",
                defaultextension=".json",
                filetypes=[("JSON sequence", "*.json"), ("All files", "*")],
            )
            if not path:
                return False
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(self._points_payload(), handle, indent=2)
                handle.write("\n")
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"Could not export: {exc}")
            return False
        self.var_status.set(f"Exported {len(self.points)} points to {os.path.basename(path)}")
        return True

    def import_points(self, path=None, replace=True):
        """Load a sequence file (the CLI format) into the list."""
        if path is None:
            from tkinter import filedialog

            path = filedialog.askopenfilename(
                parent=self.root,
                title="Import sequence",
                filetypes=[("JSON sequence", "*.json"), ("All files", "*")],
            )
            if not path:
                return False
        try:
            import cli

            points = cli.load_points(path)
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return False
        if replace and self.points and not messagebox.askyesno(
            APP_TITLE,
            f"Replace the {len(self.points)} current points with "
            f"the {len(points)} from this file?",
        ):
            return False
        if replace:
            self.points = list(points)
        else:
            self.points.extend(points)
        self._refresh_points()
        self.var_status.set(f"Imported {len(points)} points")
        return True

    def clear_points(self):
        if not self.points:
            return
        if not messagebox.askyesno(
            APP_TITLE, f"Remove all {len(self.points)} points from the sequence?"
        ):
            return
        self.points.clear()
        self._refresh_points()
        self.var_status.set("Sequence cleared")

    @staticmethod
    def _raw(value):
        return value.get() if hasattr(value, "get") else value

    def _save_point(self, index, x, y, delay, button, double, hold, window=None):
        """Validate and store an edited point. Returns True when it was saved."""
        def whole(value, label):
            try:
                number = int(str(self._raw(value)).strip())
            except (TypeError, ValueError):
                raise ValueError(f"{label} must be a whole number")
            if number < 0:
                raise ValueError(f"{label} cannot be negative")
            return number

        try:
            point = engine.Point(
                x=whole(x, "X"),
                y=whole(y, "Y"),
                delay_ms=whole(delay, "Delay"),
                hold_ms=whole(hold, "Hold"),
                button=str(self._raw(button) or ""),
                double=bool(self._raw(double)),
            )
            if point.button and point.button not in engine.BUTTONS:
                raise ValueError("button must be left, middle or right")
            if not 0 <= index < len(self.points):
                raise ValueError("that point is no longer in the list")
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return False

        self.points[index] = point
        self._refresh_points()
        children = self.tree.get_children()
        if index < len(children):
            self.tree.selection_set(children[index])
            self.tree.see(children[index])
        self.var_status.set(f"Point {index + 1} updated")
        if window is not None:
            window.destroy()
        return True

    def edit_point(self):
        """Edit the selected row (also reachable by double-clicking it)."""
        selection = self.tree.selection()
        if not selection:
            self.var_status.set("Select a point to edit")
            return
        index = self.tree.index(selection[0])
        if not 0 <= index < len(self.points):
            return
        point = self.points[index]

        window = tk.Toplevel(self.root)
        window.title(f"{APP_TITLE} — Edit point {index + 1}")
        window.transient(self.root)
        window.configure(bg=BG)
        window.resizable(False, False)

        frame = ttk.Frame(window, style="Card.TFrame", padding=12)
        frame.pack(fill="both", expand=True)
        var_x = tk.StringVar(value=str(point.x))
        var_y = tk.StringVar(value=str(point.y))
        var_delay = tk.StringVar(value=str(point.delay_ms))
        var_hold = tk.StringVar(value=str(point.hold_ms))
        var_button = tk.StringVar(value=point.button or self.var_button.get())
        var_double = tk.BooleanVar(value=point.double)

        for label, variable in (
            ("X", var_x),
            ("Y", var_y),
            ("Delay (ms)", var_delay),
            ("Hold (ms)", var_hold),
        ):
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=label, width=11).pack(side="left")
            ttk.Entry(row, textvariable=variable, width=8).pack(side="left")

        row = ttk.Frame(frame)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="Button", width=11).pack(side="left")
        ttk.Combobox(row, textvariable=var_button, values=list(engine.BUTTONS),
                     state="readonly", width=8).pack(side="left")
        ttk.Checkbutton(frame, text="Double click", variable=var_double).pack(anchor="w", pady=(4, 0))

        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(10, 0))

        def save():
            self._save_point(index, var_x, var_y, var_delay, var_button,
                             var_double, var_hold, window=window)

        ttk.Button(actions, text="Save", command=save, style="Ghost.TButton").pack(side="right")
        ttk.Button(actions, text="Cancel", command=window.destroy,
                   style="Ghost.TButton").pack(side="right", padx=6)
        window.bind("<Return>", lambda event: save())
        window.bind("<Escape>", lambda event: window.destroy())
        self._center(window)
        window.focus_force()

    def _refresh_points(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for point in self.points:
            self.tree.insert(
                "",
                "end",
                values=(
                    point.x,
                    point.y,
                    point.delay_ms,
                    point.button or "-",
                    point.double,
                    point.hold_ms,
                ),
            )

    def _sequence_mode(self):
        return self.var_mode.get().strip().lower() == "sequence"

    def build_plan(self):
        """Build a plan from the selected mode and the shared settings."""
        if self._sequence_mode():
            if not self.points:
                raise ValueError("add at least one point to the sequence")
            plan = engine.ClickPlan(
                mode=engine.SEQUENCE_MODE,
                interval_ms=self.interval_ms(),
                button=self.var_button.get(),
                hold_ms=self._read_int(self.var_hold),
                points=list(self.points),
                loops=self._read_int(self.var_loops),
                count=self._read_int(self.var_seq_count),
            )
        else:
            plan = engine.ClickPlan(
                mode=engine.INTERVAL_MODE,
                interval_ms=self.interval_ms(),
                random_offset_ms=self._read_int(self.var_offset),
                button=self.var_button.get(),
                double=self.var_double.get(),
                hold_ms=self._read_int(self.var_hold),
                count=0 if self.var_unlimited.get() else self._read_int(self.var_count, 1, 1),
                position=self.position(),
            )
        errors = plan.validate()
        if errors:
            raise ValueError("; ".join(errors))
        return plan

    # --- running ---

    def start(self):
        try:
            plan = self.build_plan()
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        if self.hotkey_listener is None and (
            plan.position is not None or plan.mode == engine.SEQUENCE_MODE
        ):
            # Fixed-point clicking moves the pointer away from the Stop button;
            # without a hotkey there may be no way back.
            if not messagebox.askyesno(
                APP_TITLE,
                "The toggle hotkey is unavailable and this plan clicks at a fixed "
                "point.\nStarting now can make the run hard to stop.\n\nStart anyway?",
            ):
                self.var_status.set("Cancelled — no hotkey to stop the run")
                return
        if self.engine is None:
            self.engine = engine.ClickEngine(backend.make_backend())
        try:
            started = self.engine.start(plan)
        except (ValueError, backend.BackendError) as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        if started:
            self.var_status.set(f"Clicking — press the hotkey to stop ({self._target_text(plan.position)})")
            self.button_start.configure(state="disabled")
            self.button_stop.configure(state="normal", style="Running.TButton")
            self._pulse()
            self._schedule("poll", 120, self._poll)

    def stop(self):
        self._unset("pulse")
        if self.engine is not None:
            self.engine.stop()
            # Show the final count: the last click may arrive between polls.
            self.var_counter.set(f"{self.engine.clicks_done} clicks")
        self.button_start.configure(state="normal", style="Accent.TButton")
        self.button_stop.configure(state="disabled", style="Stop.TButton")
        if self._sequence_mode():
            target = "the sequence points"
        else:
            target = self._target_text()
        self.var_status.set(f"Idle — next run {target}")
        self._set_exec_labels(False)

    def _poll(self):
        if self.engine is not None and self.engine.running:
            count = self.engine.clicks_done
            self.var_counter.set(f"{count} clicks")
            if count != self._last_count:
                self._last_count = count
                self._pop_counter()
            self._schedule("poll", 120, self._poll)
        else:
            self.stop()

    # --- hotkey ---

    def _start_hotkey(self):
        """Register the hotkey, keeping the previous one if the new one fails."""
        requested = self.var_hotkey.get().strip() or "F6"
        previous = self.hotkey_listener
        try:
            listener = hotkey.HotkeyListener(requested, callback=self._hotkey_pressed)
        except hotkey.HotkeyError as exc:
            self._hotkey_failed(exc, previous)
            return
        if previous is not None and previous.hotkey == listener.hotkey:
            self._hotkey_ready(listener.hotkey)
            return
        try:
            listener.start()
        except hotkey.HotkeyError as exc:
            self._hotkey_failed(exc, previous)
            return
        if previous is not None:
            previous.stop()
        self.hotkey_listener = listener
        self._hotkey_ready(listener.hotkey)

    def _hotkey_failed(self, exc, previous):
        if previous is not None:
            self.var_hotkey.set(previous.hotkey)
            self.var_status.set(f"Hotkey unavailable: {exc} (kept {previous.hotkey})")
        else:
            self.var_status.set(f"Hotkey unavailable: {exc}")

    def _hotkey_ready(self, name):
        self.var_hotkey.set(name)
        self._set_exec_labels(self.engine is not None and self.engine.running)
        if not (self.engine is not None and self.engine.running):
            self.var_status.set(f"Ready — {name.upper()} to start/stop")

    def _hotkey_pressed(self):
        # Called from the listener thread: hand control back to tkinter.
        self.root.after(0, self.toggle)

    # --- updates ---

    def _auto_update_startup(self):
        """Check once when a managed install opens; never touch a git checkout."""
        if os.environ.get("CLICKTASK_NO_UPDATE") or not self.settings.get("auto_update", True):
            return
        try:
            import updater
        except Exception:  # pragma: no cover - defensive: no updater, no check
            return
        if not updater.is_managed():
            return
        self.check_updates(manual=False)

    def check_updates(self, manual=False):
        if self._update_running:
            return
        self._update_running = True
        self._update_manual = manual
        if manual:
            self.var_update.set(f"v{VERSION} — checking…")
        threading.Thread(target=self._update_worker, args=(manual,), daemon=True).start()
        # Poll on the main thread: touching Tk from the worker thread raises
        # "main thread is not in main loop" when Tk is driven by update().
        self._schedule("update", 120, self._poll_update)

    def _poll_update(self):
        try:
            result, error = self._update_queue.get_nowait()
        except queue.Empty:
            if self._update_running:
                self._schedule("update", 120, self._poll_update)
            return
        self._update_done(self._update_manual, result, error)

    def _update_worker(self, manual):
        try:
            import updater

            release = updater.fetch_latest_release(use_cache=not manual)
            current = updater.installed_version()
            if not updater.is_newer(release["version"], current):
                result, error = {"updated": False, "version": current}, None
            else:
                outcome = updater.apply_release(release)
                result = {
                    "updated": bool(outcome.get("updated")),
                    "version": outcome.get("to", release["version"]),
                }
                error = None
        except Exception as exc:  # network, permissions, archive: all reported
            result, error = None, str(exc)
        self._update_queue.put((result, error))

    def _update_done(self, manual, result, error):
        self._update_running = False
        if error is not None:
            self.var_update.set("update check failed")
            if manual:
                messagebox.showwarning(APP_TITLE, f"Could not check for updates:\n{error}")
            return
        version = result.get("version", VERSION)
        if result.get("updated"):
            self.var_update.set(f"v{version} installed — restart to apply")
            self.var_status.set(f"Updated to {version} — restart ClickTask")
            if manual:
                messagebox.showinfo(
                    APP_TITLE,
                    f"ClickTask {version} was installed.\nRestart the app to use it.",
                )
        else:
            self.var_update.set(f"v{version} — up to date")
            if manual:
                messagebox.showinfo(APP_TITLE, f"ClickTask {version} is up to date.")

    # --- persistence ---

    def current_settings(self):
        return {
            "interval_ms": self.interval_ms(),
            "random_offset_ms": self._read_int(self.var_offset),
            "button": self.var_button.get(),
            "double": self.var_double.get(),
            "hold_ms": self._read_int(self.var_hold),
            "count": 0 if self.var_unlimited.get() else self._read_int(self.var_count, 1, 1),
            "use_fixed_position": self.var_fixed.get(),
            "position": list(self.position()) if self.position() else None,
            "hotkey": self.var_hotkey.get().strip() or "F6",
            "auto_update": self.var_auto_update.get(),
            "sequence_loops": self._read_int(self.var_loops),
            "points": [
                {
                    "x": point.x,
                    "y": point.y,
                    "delay_ms": point.delay_ms,
                    "button": point.button,
                    "double": point.double,
                    "hold_ms": point.hold_ms,
                }
                for point in self.points
            ],
            "sequence_count": self._read_int(self.var_seq_count),
        }

    def on_close(self):
        self._cleanup_after_ids()
        if self.engine is not None and self.engine.running:
            self.engine.stop()
        if self.hotkey_listener is not None:
            self.hotkey_listener.stop()
        config.save(self.current_settings())
        self.root.destroy()


def main(settings=None):
    instance = singleinstance.SingleInstance()
    if not instance.acquire():
        instance.request_raise()
        print("ClickTask is already running — bringing its window forward.")
        return 0
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        instance.release()
        print(f"ClickTask: no usable display ({exc})")
        return 1
    try:
        app = ClickTaskApp(root, settings)
        instance.listen(app.request_focus)
        app.start_ipc_poll()
        root.mainloop()
    finally:
        instance.release()
        try:
            root.destroy()
        except tk.TclError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
