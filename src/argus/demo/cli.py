"""Print the same cue timeline the HTTP server plays."""

from __future__ import annotations

import argparse
import math


def _speed(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or not 0.25 <= parsed <= 100:
        raise argparse.ArgumentTypeError("speed must be a finite number from 0.25 to 100")
    return parsed


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--scenario", choices=("s1", "s4"), default="s4")
    parser.add_argument("--speed", type=_speed, default=1.0, help="playback speed (0.25 to 100, default 1)")


def run(args: argparse.Namespace) -> int:
    from argus.demo.contracts import StartDemo
    from argus.demo.timeline import DURATION_MS, load_timeline

    settings = StartDemo(scenario=args.scenario, speed=args.speed)
    timeline = load_timeline(settings.scenario)
    print(f"{settings.scenario.upper()} demo at {settings.speed:g}x")
    for cue in timeline.cues:
        seconds = cue.at_ms / (1000 * settings.speed)
        print(f"{seconds:7.2f}s  {cue.kind:<20}  {cue.title}")
    print(f"{DURATION_MS / (1000 * settings.speed):7.2f}s  completed")
    return 0
