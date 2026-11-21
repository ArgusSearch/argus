"""`argus agent record` records a live agent session over a world; `argus agent replay` re-runs it offline."""

from __future__ import annotations

import argparse
from pathlib import Path


def configure_parser(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="agent_cmd", required=True)
    rec = sub.add_parser("record", help="run Argus with the agent live over a world (needs ANTHROPIC_API_KEY)")
    rec.add_argument("--world", type=Path, required=True)
    rec.add_argument("--out", type=Path, required=True)
    rec.add_argument(
        "--decide", choices=("approve", "deny", "none"), default="none", help="the scripted operator's decision"
    )
    rep = sub.add_parser("replay", help="re-run a recording strictly from its turns, no provider, and compare")
    rep.add_argument("--world", type=Path, required=True)
    rep.add_argument("--recording", type=Path, required=True)
    rep.add_argument("--lenient", action="store_true", help="accept a changed request hash for a known key")


def run(args: argparse.Namespace) -> int:
    from argus.agent.session import record, replay

    if args.agent_cmd == "record":
        result = record(args.world, args.out, decide=args.decide)
        runs = list(result.journal.runs.values())
        usd = sum(r.usd for r in runs)
        for r in runs:
            gate = f"{r.gate.claimed} -> {r.gate.admitted}" if r.gate else "-"
            print(
                f"{r.run_id} {r.anomaly_id} {r.status} calls={r.llm_calls} tools={r.tool_calls} {gate} USD {r.usd:.4f}"
            )
        print(f"{len(runs)} run(s), USD {usd:.4f} -> {args.out}")
        return 0
    problems = replay(args.world, args.recording, strict=not args.lenient)
    for line in problems:
        print(line)
    print("replay matches the recording" if not problems else f"{len(problems)} difference(s)")
    return 0 if not problems else 1
