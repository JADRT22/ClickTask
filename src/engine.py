# -*- coding: utf-8 -*-
"""
ClickTask - engine.py
Description: Click scheduling engine. Runs an interval-based clicker (GS Auto
             Clicker model) or an ordered click sequence, on a worker thread,
             with a monotonic clock so the rhythm does not drift.
Author: JADRT22 (https://github.com/JADRT22)
License: MIT
"""

import random
import threading
import time
from dataclasses import dataclass, field

INTERVAL_MODE = "interval"
SEQUENCE_MODE = "sequence"
MODES = (INTERVAL_MODE, SEQUENCE_MODE)

BUTTONS = ("left", "middle", "right")

# 0 means "no limit" for both `count` and `loops`.
UNLIMITED = 0


@dataclass
class Point:
    """One step of a click sequence."""

    x: int
    y: int
    delay_ms: int = 0
    button: str = ""  # empty -> inherit the plan's button
    double: bool = False
    hold_ms: int = 0  # 0 -> inherit the plan's hold


@dataclass
class ClickPlan:
    """Everything needed to run a clicking task.

    `position` is None to click wherever the cursor is, or an (x, y) tuple to
    pin the clicks to one point on screen (GS "click at fixed location").
    """

    mode: str = INTERVAL_MODE
    interval_ms: int = 100
    random_offset_ms: int = 0
    button: str = "left"
    double: bool = False
    hold_ms: int = 0
    count: int = UNLIMITED
    position: tuple = None
    points: list = field(default_factory=list)
    loops: int = UNLIMITED

    @property
    def interval_s(self):
        return max(self.interval_ms, 1) / 1000.0

    def validate(self):
        """Return a list of human-readable problems (empty list == valid)."""
        errors = []
        if self.mode not in MODES:
            errors.append("mode must be 'interval' or 'sequence'")
        if self.interval_ms < 1:
            errors.append("interval must be at least 1 ms")
        if self.random_offset_ms < 0:
            errors.append("random offset cannot be negative")
        if self.button not in BUTTONS:
            errors.append("button must be left, middle or right")
        if self.count < 0:
            errors.append("count cannot be negative")
        if self.loops < 0:
            errors.append("loops cannot be negative")
        if self.hold_ms < 0:
            errors.append("hold cannot be negative")
        if self.position is not None:
            x, y = self.position
            if x < 0 or y < 0:
                errors.append("position cannot be negative")
        if self.mode == SEQUENCE_MODE:
            if not self.points:
                errors.append("sequence mode needs at least one point")
            for index, point in enumerate(self.points, 1):
                if point.button and point.button not in BUTTONS:
                    errors.append(f"point {index}: invalid button")
                if point.delay_ms < 0:
                    errors.append(f"point {index}: delay cannot be negative")
                if point.x < 0 or point.y < 0:
                    errors.append(f"point {index}: position cannot be negative")
        return errors


class ClickEngine:
    """Runs a :class:`ClickPlan` on a daemon thread.

    `on_event(name, payload)` receives ``start``, ``click`` (clicks done so
    far), ``stop`` (total clicks) and ``error`` (exception) events. `clock`
    and `sleep` are injectable so tests run without waiting.
    """

    def __init__(self, backend, on_event=None, clock=None, sleep=None):
        self._backend = backend
        self._on_event = on_event or (lambda name, payload: None)
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.clicks_done = 0

    @property
    def running(self):
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self, plan):
        """Start a plan. Returns False when one is already running."""
        errors = plan.validate()
        if errors:
            raise ValueError("; ".join(errors))
        with self._lock:
            if self.running:
                return False
            self._stop.clear()
            self.clicks_done = 0
            # Announced before the worker exists so listeners always see
            # `start` before the first `click`.
            self._on_event("start", plan)
            self._thread = threading.Thread(
                target=self._run, args=(plan,), name="clicktask-engine", daemon=True
            )
            self._thread.start()
        return True

    def wait(self, timeout=None):
        """Block until the current run finishes (or `timeout` elapses)."""
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)

    def stop(self, timeout=3.0):
        """Ask the worker to stop and wait for it (safe to call twice)."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout)
        self._thread = None

    # --- worker internals ---

    def _run(self, plan):
        try:
            if plan.mode == SEQUENCE_MODE:
                self._run_sequence(plan)
            else:
                self._run_interval(plan)
        except Exception as exc:  # a dead backend must not take the app down
            self._on_event("error", exc)
        finally:
            self._on_event("stop", self.clicks_done)

    def _jitter_s(self, plan):
        """Uniform jitter in [-offset, +offset], keeping the slot at >= 1 ms."""
        if plan.random_offset_ms <= 0:
            return plan.interval_s
        delta = random.uniform(-plan.random_offset_ms, plan.random_offset_ms) / 1000.0
        return max(plan.interval_s + delta, 0.001)

    def _run_interval(self, plan):
        next_at = self._clock()
        done = 0
        while not self._stop.is_set():
            self._click(plan.position, plan.button, plan.double, plan.hold_ms)
            done += 1
            self.clicks_done = done
            self._on_event("click", done)
            if plan.count != UNLIMITED and done >= plan.count:
                return
            next_at += self._jitter_s(plan)
            now = self._clock()
            if next_at < now:
                next_at = now  # fell behind (system stall): resume, never burst
            self._sleep(next_at - now)

    def _run_sequence(self, plan):
        done = 0
        loops = 0
        while not self._stop.is_set():
            for point in plan.points:
                if self._stop.is_set():
                    return
                if point.delay_ms:
                    self._sleep(point.delay_ms / 1000.0)
                self._click(
                    (point.x, point.y),
                    point.button or plan.button,
                    point.double,
                    point.hold_ms or plan.hold_ms,
                )
                done += 1
                self.clicks_done = done
                self._on_event("click", done)
                if plan.count != UNLIMITED and done >= plan.count:
                    return
            loops += 1
            if plan.loops != UNLIMITED and loops >= plan.loops:
                return

    def _click(self, position, button, double, hold_ms):
        if position is not None:
            self._backend.move(int(position[0]), int(position[1]))
        self._backend.click(button, double=double, hold_ms=hold_ms)
