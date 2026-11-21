"""Print the same cue timeline the HTTP server plays."""

from __future__ import annotations

import argparse
import math
import sys


def _speed(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or not 0.25 <= parsed <= 100:
        raise argparse.ArgumentTypeError("speed must be a finite number from 0.25 to 100")
    return parsed


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--scenario", choices=("s1", "s2", "s4"), default="s4")
    parser.add_argument("--speed", type=_speed, default=1.0, help="playback speed (0.25 to 100, default 1)")
    parser.add_argument("--variant", choices=("legacy", "agent"), default="legacy")


def run(args: argparse.Namespace) -> int:
    from argus.demo.agent import load_agent_timeline
    from argus.demo.contracts import StartDemo
    from argus.demo.timeline import Timeline, load_timeline

    settings = StartDemo(scenario=args.scenario, speed=args.speed, variant=args.variant)
    try:
        timeline = (
            load_agent_timeline(settings.scenario) if settings.variant == "agent" else load_timeline(settings.scenario)
        )
    except (OSError, ValueError) as exc:
        print(f"Demo recording unavailable. {exc}", file=sys.stderr)
        return 1
    variant = "" if isinstance(timeline, Timeline) else " agent"
    print(f"{settings.scenario.upper()}{variant} demo at {settings.speed:g}x")
    for cue in timeline.cues:
        seconds = cue.at_ms / (1000 * settings.speed)
        print(f"{seconds:7.2f}s  {cue.kind:<20}  {cue.title}")
    note = " (excluding the approval hold)" if timeline.approval_index is not None else ""
    print(f"{timeline.duration_ms / (1000 * settings.speed):7.2f}s  completed{note}")
    return 0
