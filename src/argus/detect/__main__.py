"""Run the watcher over a world and print what it opened.

    uv run python -m argus.detect --world runs/s1-7/world.duckdb [--events events.jsonl]

Without --from/--to it ticks over the live window from the world's manifest (live_start .. world_end).
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

from argus.detect.watcher import EventRecorder, Watcher, WatcherConfig, summarize
from argus.graph.store import SEED_GRAPH, load_seed_graph
from argus.semantic.runner import Runner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m argus.detect", description="Argus watcher over a world")
    parser.add_argument("--world", type=Path, required=True, help="path to world.duckdb")
    parser.add_argument("--graph", type=Path, default=SEED_GRAPH, help="seed graph YAML")
    parser.add_argument("--from", dest="start", type=datetime.fromisoformat, help="first as_of (default live_start)")
    parser.add_argument("--to", dest="end", type=datetime.fromisoformat, help="last as_of (default world end + 1 h)")
    parser.add_argument("--budget", type=int, default=WatcherConfig.budget, help="attention looks per tick")
    parser.add_argument("--events", type=Path, help="write the C5 events as JSON lines")
    args = parser.parse_args(argv)

    manifest_path = args.world.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    lag = int(manifest.get("delivery_lag_hours", WatcherConfig.lag_hours))
    start = args.start or datetime.fromisoformat(manifest["live_start"])
    end = args.end or datetime.fromisoformat(manifest["world_end"]) + timedelta(hours=1)

    runner = Runner(args.world)
    recorder = EventRecorder()
    watcher = Watcher(runner, load_seed_graph(args.graph), WatcherConfig(lag_hours=lag, budget=args.budget), recorder)
    started = time.perf_counter()
    ticks = 0
    for report in watcher.run(start, end):
        ticks += 1
        for note in report.notes:
            print(f"{report.as_of:%m-%d %H:%M} note    {note.reason}")
        for anomaly in report.opened:
            print(f"{report.as_of:%m-%d %H:%M} OPEN    {summarize(anomaly)}")
        for anomaly in report.resolved:
            print(f"{report.as_of:%m-%d %H:%M} resolve {anomaly.id} {anomaly.node} {anomaly.segment or 'total'}")
    seconds = time.perf_counter() - started
    if args.events:
        args.events.write_text("".join(e.model_dump_json() + "\n" for e in recorder.events))
    f = watcher.funnel
    print(
        json.dumps(
            {
                "ticks": ticks,
                "anomalies": len(watcher.anomalies),
                "still_open": len(watcher.open),
                "notes": len(watcher.notes),
                "funnel": {"series": f.series, "wiggles": f.wiggles, "triggers": f.triggers, "opened": f.opened},
                "events": len(recorder.events),
                "queries": runner.query_count,
                "seconds": round(seconds, 2),
            }
        )
    )
    runner.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
