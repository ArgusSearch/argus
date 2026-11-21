"""`argus-bench`: the scorecard, single sealed cases, the blind challenge and a judge's hash check.

argus-bench                                  every built scenario x 3 seeds, every available agent
argus-bench run --scenarios s1,s3 --runs 5   choose scenarios and seeds
argus-bench s1 --seed 7 [--record fixtures]  S1 exit criteria in detail (lane lead's S1 bench)
argus-bench case s3 --seed 7                 one sealed case of any scenario, verbose (also `argus-bench s3`)
argus-bench blind [--seed N]                 hidden scenario, commitment first, then reveal
argus-bench record s3 --seed 1 --out DIR     a replayable Argus run of any scenario (fixtures/<scenario>)
argus-bench verify runs/bench/s1-1           recompute a case's commitment from its reveal
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from argus.contracts.events import BenchProgressPayload, ChallengeStatePayload
from bench.agents import Agent, AgentUnavailable, resolve_agent
from bench.blind import blind_challenge
from bench.claims import Claim, claims_from_output
from bench.grade import RunGrade
from bench.record import record
from bench.runner import BUILT_SCENARIOS, DEFAULT_OUT, grade_case, prepare_case, reveal, run_agent, run_bench
from bench.s1 import record_fixtures, run_s1
from bench.scorecard import render
from bench.sealed import verify

DEFAULT_AGENTS = "argus,threshold"
CASE_SCENARIOS = (*BUILT_SCENARIOS, "s5")


def _agents(spec: str) -> tuple[list[Agent], dict[str, str]]:
    agents: list[Agent] = []
    unavailable: dict[str, str] = {}
    for name in [s.strip() for s in spec.split(",") if s.strip()]:
        try:
            agents.append(resolve_agent(name))
        except AgentUnavailable as exc:
            unavailable[name] = str(exc)
    return agents, unavailable


def _require_agents(spec: str) -> tuple[list[Agent], dict[str, str]]:
    agents, unavailable = _agents(spec)
    for name, why in unavailable.items():
        print(f"agent {name}: not available ({why})", file=sys.stderr)
    if not agents:
        raise SystemExit("no agent can run; try --agents threshold")
    return agents, unavailable


def _claim_line(c: Claim) -> str:
    seg = ", ".join(f"{k}={v}" for k, v in sorted(c.segment.items())) or "all"
    cite = f"  evidence {', '.join(c.evidence)}" if c.evidence else ""
    out = f"  ruled out {', '.join(c.ruled_out)}" if c.ruled_out else ""
    kind = "PAGE" if c.is_page else c.source
    return f"  {c.detected_at:%a %H:%M}  {kind:<8} {c.verdict.value:<15} {c.node or '-'} [{seg}]{cite}{out}"


def _grade_lines(g: RunGrade) -> list[str]:
    lines = [f"  {e.event_id:<28} expected {e.expected:<15} grade {e.grade}  {e.label}" for e in g.events]
    if not g.events:
        lines.append("  (nothing injected)")
    lines.append(
        f"  pages {g.pages}, false alarms {len(g.false_alarms)}, truth verified {g.verified}, "
        f"{'PASS' if g.passed else 'FAIL'}" + (f", agent error: {g.error}" if g.error else "")
    )
    return lines


def cmd_run(args: argparse.Namespace) -> int:
    agents, unavailable = _require_agents(args.agents)
    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    seeds = (
        [int(s) for s in args.seeds.split(",")]
        if args.seeds
        else list(range(args.base_seed, args.base_seed + args.runs))
    )

    def progress(p: BenchProgressPayload) -> None:
        last = p.last
        if last.get("phase") == "committed":
            print(f"sealed {len(scenarios) * len(seeds)} worlds; bench commitment {last['bench_commitment']}")
        elif last.get("phase") == "ran":
            print(f"[{p.done}/{p.total}] {last['agent']} on {last['case']} in {last['seconds']}s")

    card = run_bench(scenarios, seeds, agents, args.out, unavailable=unavailable, progress=progress)
    print()
    print(render(card))
    if args.json:
        args.json.write_text(card.model_dump_json(indent=2) + "\n")
    print(f"\nscorecard: {args.out / 'scorecard.json'}")
    return 0


def cmd_case(args: argparse.Namespace) -> int:
    agents, unavailable = _require_agents(args.agents)
    first = args.agents.split(",")[0].strip()
    if args.record and first in unavailable:
        # `--record` writes fixtures for the first requested agent; never let a fallback stand in for it.
        raise SystemExit(f"cannot record: agent {first} is not available ({unavailable[first]})")
    case = prepare_case(args.scenario, args.seed, args.out)
    print(f"case {case.case}: truth sealed, commitment {case.envelope.commitment}")
    results = [(agent, *run_agent(case, agent)) for agent in agents]
    verified = reveal(case)
    for agent, output, seconds, error in results:
        g = grade_case(case, agent.name, output, seconds, verified, error)
        print(f"\n{agent.name} ({seconds:.1f}s):")
        for c in claims_from_output(output):
            print(_claim_line(c))
        print("\n".join(_grade_lines(g)))
        if args.record and agent is agents[0]:
            target = args.record
            output.write(target)
            (target / "grade.json").write_text(g.model_dump_json(indent=2) + "\n")
            for name in ("commitment.json", "reveal.json"):
                shutil.copy(case.dir / name, target / name)
            print(f"  recorded to {target}")
    return 0


def cmd_blind(args: argparse.Namespace) -> int:
    agents, _ = _require_agents(args.agents)
    agent = agents[0]

    def emit(p: ChallengeStatePayload) -> None:
        if p.state == "committed":
            print(f"hidden scenario sealed. commitment: {p.commitment}")
        elif p.state == "running":
            print(f"{agent.name} is watching the live window ...")

    menu = [s.strip() for s in args.menu.split(",") if s.strip()]
    result = blind_challenge(agent, args.out, seed=args.seed, scenario=args.scenario, menu=menu, emit=emit)
    print(f"\n{agent.name} says:")
    for c in result.claims:
        print(_claim_line(c))
    if not result.claims:
        print("  nothing is broken")
    print(f"\nreveal: scenario {result.scenario}, seed {result.seed}")
    print("\n".join(_grade_lines(result.grade)))
    print(f"\ncheck it yourself: argus-bench verify {result.case_dir}")
    return 0


def cmd_s1(args: argparse.Namespace) -> int:
    """S1 end to end with its six exit criteria (not sealed: the criteria need the live runtime object)."""
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


def cmd_record(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    g = record(args.scenario, args.seed, args.out, args.work)
    print(f"{args.scenario} seed {args.seed}: recorded to {args.out} ({time.perf_counter() - started:.1f} s)")
    print("\n".join(_grade_lines(g)))
    return 0 if g.passed else 1


def cmd_verify(args: argparse.Namespace) -> int:
    commit = json.loads((args.case / "commitment.json").read_text())
    doc = json.loads((args.case / "reveal.json").read_text())
    ok = verify(commit["commitment"], doc["nonce"], doc["payload"])
    print(f"commitment {commit['commitment']}")
    print(f"recomputed sha256(nonce + '\\n' + payload): {'match' if ok else 'MISMATCH'}")
    return 0 if ok else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="argus-bench", description="Argus bench: scorecard and blind challenge")
    sub = parser.add_subparsers(dest="cmd")

    def common(p: argparse.ArgumentParser, agents: str = DEFAULT_AGENTS) -> None:
        p.add_argument("--agents", default=agents, help="comma list: argus, threshold, module:fn, cmd:<template>")
        p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where worlds, seals and results go")

    run = sub.add_parser("run", help="every scenario x seed, then the scorecard (default)")
    common(run)
    run.add_argument("--scenarios", default=",".join(CASE_SCENARIOS))
    run.add_argument("--runs", type=int, default=3, help="seeds per scenario")
    run.add_argument("--base-seed", type=int, default=1)
    run.add_argument("--seeds", default="", help="explicit comma list, overrides --runs")
    run.add_argument("--json", type=Path, default=None, help="also write the scorecard JSON here")
    run.set_defaults(fn=cmd_run)

    case = sub.add_parser("case", help="one sealed case, verbose")
    case.add_argument("scenario", choices=CASE_SCENARIOS)
    case.add_argument("--seed", type=int, default=7)
    case.add_argument("--record", type=Path, default=None, help="write the first agent's output, grade and seal here")
    common(case)
    case.set_defaults(fn=cmd_case)

    blind = sub.add_parser("blind", help="hidden scenario: commit, run, reveal")
    blind.add_argument("--seed", type=int, default=None)
    blind.add_argument("--scenario", default=None, help="force a scenario (rehearsal only)")
    blind.add_argument("--menu", default=",".join(BUILT_SCENARIOS))
    common(blind, agents="argus,threshold")
    blind.set_defaults(fn=cmd_blind)

    s1 = sub.add_parser("s1", help="S1 PayCo outage + release red herring, six exit criteria")
    s1.add_argument("--seed", type=int, action="append", help="repeatable; default 7")
    s1.add_argument("--runs-dir", type=Path, default=Path("runs"))
    s1.add_argument("--record", type=Path, help="copy the run's outputs into this fixtures directory")
    s1.set_defaults(fn=cmd_s1)

    rec = sub.add_parser("record", help="a replayable Argus run of one scenario, graded after it is written")
    rec.add_argument("scenario", choices=CASE_SCENARIOS)
    rec.add_argument("--seed", type=int, default=1)
    rec.add_argument("--out", type=Path, required=True, help="recording directory, e.g. fixtures/s3")
    rec.add_argument("--work", type=Path, default=DEFAULT_OUT / "record", help="where the sealed world goes")
    rec.set_defaults(fn=cmd_record)

    ver = sub.add_parser("verify", help="recompute a case's commitment from its reveal")
    ver.add_argument("case", type=Path)
    ver.set_defaults(fn=cmd_verify)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in CASE_SCENARIOS and argv[0] != "s1":  # `argus-bench s3 --seed 7`
        argv = ["case", *argv]
    if not argv or argv[0].startswith("-"):
        argv = ["run", *argv]
    args = _parser().parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
