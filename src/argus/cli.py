"""`argus run --world W` runs the tick loop over a world; `argus api` serves REST and SSE."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from argus.demo import cli as demo_cli


def main(argv: list[str] | None = None) -> int:
    from argus.counterfactual.__main__ import add_arguments
    from argus.counterfactual.__main__ import run as run_counterfactual

    parser = argparse.ArgumentParser(prog="argus", description="Argus, the analyst that never sleeps")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="run every tick of a world's live window and write the outputs")
    run.add_argument("--world", type=Path, required=True, help="world.duckdb (truth is never needed)")
    run.add_argument("--out", type=Path, help="default: <world dir>/argus")
    run.add_argument("--stage", type=int, choices=(1, 2), default=2, help="investigator stage (default: 2)")

    api = sub.add_parser("api", help="serve the REST API and the SSE stream")
    api.add_argument("--world", type=Path, help="run live over this world; default: replay fixtures/")
    api.add_argument("--replay", type=Path, help="fixtures directory to replay (default: fixtures/)")
    api.add_argument("--tick-seconds", type=float, default=2.0, help="wall seconds per simulated hour")
    api.add_argument("--stage", type=int, choices=(1, 2), default=2, help="live investigator stage (default: 2)")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)
    demo_cli.configure_parser(sub.add_parser("demo", help="print the demo playback timeline"))
    add_arguments(sub.add_parser("counterfactual", help="replay a MockMart incident with its named cause switched off"))
    args = parser.parse_args(argv)
    if args.cmd == "counterfactual":
        return run_counterfactual(args)

    if args.cmd == "demo":
        return demo_cli.run(args)

    if args.cmd == "run":
        from argus.runtime.loop import Runtime

        runtime = Runtime(args.world, stage=args.stage)
        runtime.run()
        out = args.out or args.world.parent / "argus"
        runtime.export(out)
        summary = {
            "ticks": len(runtime.ticks()),
            "stage": runtime.stage,
            "anomalies": len(runtime.anomalies),
            "incidents": [
                {"id": i.id, "verdict": i.verdict.value, "title": i.title, "state": i.state.value}
                for i in runtime.book.incidents.values()
            ],
            "notes": len(runtime.book.notes),
            "receipts": len(runtime.runner.receipts),
            "stage_one_fallbacks": runtime.fallbacks,
            "out": str(out),
        }
        print(json.dumps(summary, indent=2))
        return 0

    import uvicorn

    from argus.api.app import create_app
    from argus.api.sources import FIXTURES, LiveSource, ReplaySource

    source = (
        LiveSource(args.world, args.tick_seconds, stage=args.stage)
        if args.world
        else ReplaySource(args.replay or FIXTURES, args.tick_seconds, loop=True)
    )
    uvicorn.run(create_app(source), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
