# -*- coding: utf-8 -*-
"""
ClickTask - cli.py
Description: Headless CLI: `click` for interval runs, `seq` for a saved point
             sequence, both with --dry-run so the plan can be checked without
             moving the pointer. No GUI, no display needed for --dry-run.
Author: JADRT22 (https://github.com/JADRT22)
License: MIT
"""

import argparse
import json
import re
import sys

import backend
import engine

VERSION = "1.0.0"

INTERVAL_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(ms|s|m|h)?\s*$", re.IGNORECASE)
INTERVAL_UNITS = {"ms": 1.0, "s": 1000.0, "m": 60000.0, "h": 3600000.0}

EXIT_OK = 0
EXIT_BACKEND = 1
EXIT_USAGE = 2
EXIT_INTERRUPT = 130


def parse_interval(text):
    """Parse "100", "100ms", "1.5s", "2m", "1h" into whole milliseconds."""
    match = INTERVAL_RE.match(str(text))
    if not match:
        raise ValueError(
            f"invalid interval: {text!r} (use 100, 100ms, 1.5s, 2m or 1h)"
        )
    value = float(match.group(1))
    unit = (match.group(2) or "ms").lower()
    millis = int(round(value * INTERVAL_UNITS[unit]))
    if millis < 1:
        raise ValueError("interval must be at least 1 ms")
    return millis


def parse_point(text):
    """Parse "800,600" into (800, 600)."""
    match = re.match(r"^\s*(-?\d+)\s*[,x ]\s*(-?\d+)\s*$", str(text))
    if not match:
        raise ValueError(f"invalid position: {text!r} (use X,Y)")
    x, y = int(match.group(1)), int(match.group(2))
    if x < 0 or y < 0:
        raise ValueError("position cannot be negative")
    return (x, y)


def load_points(path):
    """Read a sequence file: a JSON list of points, or a {"points": [...]} dict."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    except ValueError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc

    raw_points = data.get("points") if isinstance(data, dict) else data
    if not isinstance(raw_points, list) or not raw_points:
        raise ValueError(f"{path} must contain a non-empty list of points")

    points = []
    for index, item in enumerate(raw_points, 1):
        if not isinstance(item, dict) or "x" not in item or "y" not in item:
            raise ValueError(f"point {index} needs x and y")
        click = engine.Point(
            x=int(item["x"]),
            y=int(item["y"]),
            delay_ms=int(item.get("delay_ms", 0)),
            button=item.get("button", ""),
            double=bool(item.get("double", False)),
            hold_ms=int(item.get("hold_ms", 0)),
        )
        points.append(click)
    return points


def build_parser():
    parser = argparse.ArgumentParser(
        prog="clicktask",
        description="Interval auto clicker for X11 (GS Auto Clicker model).",
    )
    parser.add_argument("--version", action="version", version=f"ClickTask {VERSION}")
    subparsers = parser.add_subparsers(dest="command")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be clicked instead of injecting input",
    )
    common.add_argument("--display", default=None, help="X display (default: $DISPLAY)")

    click = subparsers.add_parser("click", parents=[common], help="click at an interval")
    click.add_argument(
        "--interval", default="100ms", help="100, 250ms, 1.5s, 2m (default: 100ms)"
    )
    click.add_argument(
        "--count", default="0", help="number of clicks, 0 = until Ctrl+C (default: 0)"
    )
    click.add_argument(
        "--button", default="left", choices=list(engine.BUTTONS), help="mouse button"
    )
    click.add_argument("--double", action="store_true", help="send double clicks")
    click.add_argument("--hold", default="0", help="hold each press for N ms")
    click.add_argument(
        "--at", default=None, metavar="X,Y", help="fixed position (default: current cursor)"
    )

    seq = subparsers.add_parser("seq", parents=[common], help="play a point sequence")
    seq.add_argument("file", help="JSON list of points (x, y, delay_ms, button, double)")
    seq.add_argument("--loops", default="0", help="sequence loops, 0 = unlimited")
    seq.add_argument("--count", default="0", help="stop after N clicks, 0 = unlimited")
    seq.add_argument("--button", default="left", choices=list(engine.BUTTONS))
    seq.add_argument("--interval", default="100ms", help="default delay between points")

    return parser


def parse_number(text, flag):
    """Parse a non-negative integer flag, naming it in the error message."""
    try:
        value = int(str(text).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{flag} must be a whole number")
    if value < 0:
        raise ValueError(f"{flag} cannot be negative")
    return value


def plan_from_args(args):
    """Turn parsed CLI arguments into a :class:`engine.ClickPlan`."""
    if args.command == "click":
        interval_ms = parse_interval(args.interval)
        position = parse_point(args.at) if args.at else None
        plan = engine.ClickPlan(
            mode=engine.INTERVAL_MODE,
            interval_ms=interval_ms,
            button=args.button,
            double=args.double,
            hold_ms=parse_number(args.hold, "--hold"),
            count=parse_number(args.count, "--count"),
            position=position,
        )
    else:
        default_interval = parse_interval(args.interval)
        points = load_points(args.file)
        for point in points:
            if point.delay_ms == 0:
                point.delay_ms = default_interval
        plan = engine.ClickPlan(
            mode=engine.SEQUENCE_MODE,
            interval_ms=default_interval,
            button=args.button,
            points=points,
            loops=parse_number(args.loops, "--loops"),
            count=parse_number(args.count, "--count"),
        )
    errors = plan.validate()
    if errors:
        raise ValueError("; ".join(errors))
    return plan


def run(plan, dry_run=False, display_name=None, out=None, engine_factory=None):
    """Execute a plan to completion. Returns a process exit code."""
    out = out or sys.stdout
    try:
        device = backend.make_backend(dry_run=dry_run, display_name=display_name)
    except backend.BackendError as exc:
        print(f"clicktask: {exc}", file=sys.stderr)
        return EXIT_BACKEND

    def on_event(name, payload):
        if name == "click":
            if dry_run:
                print(f"[{payload}] {device.describe()[-1]}", file=out)
            elif payload % 25 == 0:
                print(f"{payload} clicks", file=out)
        elif name == "error":
            print(f"clicktask: {payload}", file=sys.stderr)

    runner = (engine_factory or engine.ClickEngine)(device, on_event=on_event)
    try:
        runner.start(plan)
        runner.wait()
    except KeyboardInterrupt:
        runner.stop()
        print("stopped", file=out)
        return EXIT_INTERRUPT
    finally:
        runner.stop()
        device.close()
    return EXIT_OK


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return EXIT_OK
    try:
        plan = plan_from_args(args)
    except ValueError as exc:
        print(f"clicktask: {exc}", file=sys.stderr)
        return EXIT_USAGE
    return run(plan, dry_run=args.dry_run, display_name=args.display)


if __name__ == "__main__":
    sys.exit(main())
