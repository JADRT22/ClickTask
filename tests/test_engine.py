# -*- coding: utf-8 -*-
"""
ClickTask - test_engine.py
Description: Engine tests: click counts, interval scheduling without drift,
             double clicks, fixed vs cursor position, sequence order/delays/
             loops and error propagation. No display or real sleeping needed.
Author: JADRT22 (https://github.com/JADRT22)
License: MIT
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import engine  # noqa: E402


class FakeClock:
    """Monotonic stand-in: sleeping advances the clock instead of waiting."""

    def __init__(self):
        self.now = 0.0

    def clock(self):
        return self.now

    def sleep(self, seconds):
        if seconds > 0:
            self.now += seconds


class FakeBackend:
    def __init__(self, fail_after=None):
        self.calls = []
        self.moves = []
        self.fail_after = fail_after

    def click(self, button="left", double=False, hold_ms=0):
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise RuntimeError("device gone")
        self.calls.append((button, double, hold_ms))

    def move(self, x, y):
        self.moves.append((x, y))

    def position(self):
        return (0, 0)


def interval_plan(**overrides):
    settings = dict(mode=engine.INTERVAL_MODE, interval_ms=100, count=3)
    settings.update(overrides)
    return engine.ClickPlan(**settings)


class EngineIntervalTests(unittest.TestCase):
    def run_plan(self, plan):
        clock = FakeClock()
        device = FakeBackend()
        events = []
        runner = engine.ClickEngine(
            device, on_event=lambda name, payload: events.append((name, payload)),
            clock=clock.clock, sleep=clock.sleep,
        )
        runner.start(plan)
        runner.wait(5)
        return runner, device, clock, events

    def test_clicks_the_requested_number_of_times(self):
        runner, device, _clock, _events = self.run_plan(interval_plan(count=3))
        self.assertEqual(len(device.calls), 3)
        self.assertEqual(runner.clicks_done, 3)

    def test_interval_is_honored_between_clicks(self):
        _runner, _device, clock, _events = self.run_plan(interval_plan(count=4, interval_ms=100))
        # 4 clicks need 3 gaps, so the fake clock must be at 300 ms.
        self.assertAlmostEqual(clock.now, 0.3, places=6)

    def test_pass_through_of_button_double_and_hold(self):
        clock = FakeClock()
        device = FakeBackend()
        runner = engine.ClickEngine(device, clock=clock.clock, sleep=clock.sleep)
        runner.start(interval_plan(count=1, button="right", double=True, hold_ms=15))
        runner.wait(5)
        self.assertEqual(device.calls, [("right", True, 15)])

    def test_fixed_position_moves_before_each_click(self):
        _runner, device, _clock, _events = self.run_plan(
            interval_plan(count=2, position=(640, 480))
        )
        self.assertEqual(device.moves, [(640, 480), (640, 480)])

    def test_cursor_mode_does_not_move_the_pointer(self):
        _runner, device, _clock, _events = self.run_plan(interval_plan(count=2))
        self.assertEqual(device.moves, [])

    def test_random_offset_without_offset_keeps_exact_intervals(self):
        _runner, _device, clock, _events = self.run_plan(
            interval_plan(count=4, interval_ms=100, random_offset_ms=0)
        )
        self.assertAlmostEqual(clock.now, 0.3, places=6)

    def test_random_offset_varies_the_interval_and_never_drops_below_1ms(self):
        seen = []

        for seed in range(40):
            clock = FakeClock()
            device = FakeBackend()
            runner = engine.ClickEngine(
                device, clock=clock.clock, sleep=clock.sleep,
                on_event=lambda name, payload: None,
            )
            runner.start(
                engine.ClickPlan(interval_ms=100, random_offset_ms=40, count=3)
            )
            runner.wait(5)
            # Two gaps between three clicks.
            seen.append(clock.now)

        distinct = sorted(set(round(total, 3) for total in seen))
        self.assertGreater(len(distinct), 1)
        # Two gaps, each 100 ± 40 ms, floor 1 ms.
        self.assertTrue(all(0.12 <= total <= 0.28 for total in distinct))

    def test_events_reported_in_order(self):
        _runner, _device, _clock, events = self.run_plan(interval_plan(count=2))
        names = [name for name, _payload in events]
        self.assertEqual(names, ["start", "click", "click", "stop"])
        self.assertEqual(events[-1][1], 2)

    def test_infinite_run_can_be_stopped(self):
        device = FakeBackend()
        runner = engine.ClickEngine(device)
        runner.start(engine.ClickPlan(interval_ms=5, count=0))
        deadline = time.monotonic() + 2
        while runner.clicks_done < 5 and time.monotonic() < deadline:
            time.sleep(0.01)
        runner.stop()
        self.assertGreaterEqual(runner.clicks_done, 5)
        self.assertFalse(runner.running)

    def test_backend_failure_is_reported_not_raised(self):
        device = FakeBackend(fail_after=1)
        events = []
        runner = engine.ClickEngine(
            device, on_event=lambda name, payload: events.append((name, payload))
        )
        runner.start(engine.ClickPlan(interval_ms=5, count=50))
        runner.wait(5)
        self.assertIn("error", [name for name, _payload in events])
        self.assertEqual(events[-1][0], "stop")
        self.assertFalse(runner.running)


class EngineSequenceTests(unittest.TestCase):
    def test_sequence_order_delays_and_loops(self):
        clock = FakeClock()
        device = FakeBackend()
        plan = engine.ClickPlan(
            mode=engine.SEQUENCE_MODE,
            interval_ms=100,
            loops=2,
            points=[
                engine.Point(x=10, y=20, delay_ms=0),
                engine.Point(x=30, y=40, delay_ms=50),
            ],
        )
        runner = engine.ClickEngine(device, clock=clock.clock, sleep=clock.sleep)
        runner.start(plan)
        runner.wait(5)

        self.assertEqual(device.moves, [(10, 20), (30, 40), (10, 20), (30, 40)])
        self.assertEqual(len(device.calls), 4)
        # Two loops, one 50 ms delay each.
        self.assertAlmostEqual(clock.now, 0.1, places=6)

    def test_per_point_button_and_double_override_plan(self):
        device = FakeBackend()
        plan = engine.ClickPlan(
            mode=engine.SEQUENCE_MODE,
            points=[
                engine.Point(x=1, y=1, button="right", double=True),
                engine.Point(x=2, y=2),
            ],
            loops=1,
        )
        runner = engine.ClickEngine(device)
        runner.start(plan)
        runner.wait(5)
        self.assertEqual(device.calls, [("right", True, 0), ("left", False, 0)])

    def test_count_caps_a_sequence(self):
        device = FakeBackend()
        plan = engine.ClickPlan(
            mode=engine.SEQUENCE_MODE,
            loops=0,
            count=3,
            points=[engine.Point(x=5, y=5), engine.Point(x=6, y=6)],
        )
        runner = engine.ClickEngine(device)
        runner.start(plan)
        runner.wait(5)
        self.assertEqual(len(device.calls), 3)


class PlanValidationTests(unittest.TestCase):
    def test_default_plan_is_valid(self):
        self.assertEqual(engine.ClickPlan().validate(), [])

    def test_sequence_without_points_is_rejected(self):
        plan = engine.ClickPlan(mode=engine.SEQUENCE_MODE)
        self.assertTrue(any("at least one point" in error for error in plan.validate()))

    def test_bad_values_are_rejected(self):
        cases = [
            engine.ClickPlan(interval_ms=0),
            engine.ClickPlan(button="thumb"),
            engine.ClickPlan(count=-1),
            engine.ClickPlan(random_offset_ms=-5),
            engine.ClickPlan(position=(-5, 3)),
            engine.ClickPlan(
                mode=engine.SEQUENCE_MODE,
                points=[engine.Point(x=1, y=1, button="thumb")],
            ),
            engine.ClickPlan(
                mode=engine.SEQUENCE_MODE,
                points=[engine.Point(x=-1, y=1)],
            ),
        ]
        for plan in cases:
            with self.subTest(plan=plan):
                self.assertNotEqual(plan.validate(), [])

    def test_start_rejects_invalid_plan(self):
        runner = engine.ClickEngine(FakeBackend())
        with self.assertRaises(ValueError):
            runner.start(engine.ClickPlan(interval_ms=0))

    def test_start_refuses_while_running(self):
        runner = engine.ClickEngine(FakeBackend())
        runner.start(engine.ClickPlan(interval_ms=5))
        try:
            self.assertFalse(runner.start(engine.ClickPlan(interval_ms=5)))
        finally:
            runner.stop()


if __name__ == "__main__":
    unittest.main()
