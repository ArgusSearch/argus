"""`argus-bench s1 --seed 7` runs S1 end to end and grades it against the hidden truth."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from bench.s1 import record_fixtures, run_s1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="argus-bench", description="Argus bench (reads the hidden truth)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    s1 = sub.add_parser("s1", help="S1 PayCo outage + release red herring, graded against truth")
    s1.add_argument("--seed", type=int, action="append", help="repeatable; default 7")
    s1.add_argument("--runs-dir", type=Path, default=Path("runs"))
    s1.add_argument("--record", type=Path, help="copy the run's outputs into this fixtures directory")
    args = parser.parse_args(argv)

    seeds = args.seed or [7]
    all_passed = True
    for seed in seeds:
        started = time.perf_counter()
        run = run_s1(seed, args.runs_dir / f"s1-{seed}")
        t = run.truth
        print(
            f"S1 seed {seed}: PayCo DE-android success {t['magnitude']['success_rate_normal']:.2f} -> "
            f"{t['magnitude']['success_rate_fault']:.2f} from {t['start_ts']:%Y-%m-%d %H:%M} to {t['end_ts']:%H:%M} "
            f"(hidden truth, read by the bench only)"
        )
        for c in run.criteria:
            print(f"  {'PASS' if c.passed else 'FAIL'}  {c.id:<22} {c.detail}")
        reports = sorted((run.out / "argus" / "reports").glob("*.md"))
        print(f"  report: {reports[0] if reports else '-'}   ({time.perf_counter() - started:.1f} s)")
        all_passed &= run.passed
        if args.record:
            record_fixtures(run, args.record)
            print(f"  fixtures recorded to {args.record}")
    print("ALL PASS" if all_passed else "SOME CRITERIA FAILED")
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
