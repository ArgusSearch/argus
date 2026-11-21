"""`mockmart generate --scenario s1 --seed 7 --out runs/s1-7`"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mockmart.scenarios import SCENARIOS
from mockmart.sim import WorldConfig
from mockmart.world import generate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mockmart", description="MockMart world generator")
    sub = parser.add_subparsers(dest="cmd", required=True)
    gen = sub.add_parser("generate", help="write world.duckdb, truth.duckdb and manifest.json")
    gen.add_argument("--scenario", default="s1", choices=sorted(SCENARIOS))
    gen.add_argument("--seed", type=int, default=7)
    gen.add_argument("--days", type=int, default=WorldConfig.days)
    gen.add_argument("--live-days", type=int, default=WorldConfig.live_days)
    gen.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    cfg = WorldConfig(seed=args.seed, days=args.days, live_days=args.live_days)
    paths = generate(args.scenario, cfg, args.out)
    print(json.dumps({"world": str(paths.world), "manifest": json.loads(paths.manifest.read_text())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
