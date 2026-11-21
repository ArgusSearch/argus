"""Run the bench: seal every world, run every agent, reveal, verify and grade.

Layout of one case under the output root:

    <case>/world/world.duckdb, manifest.json   the only paths an agent receives
    <case>/sealed/truth.duckdb                 hidden truth, moved out of the world dir right after generation
    <case>/commitment.json                     written before any agent runs
    <case>/reveal.json                         nonce and canonical truth, written after all agents ran
    <case>/agents/<agent>/                     the agent's output in the `cmd:` file layout
    commitment.json, scorecard.json            bench-wide commitment and the scorecard

All worlds are generated and sealed first, and the bench commitment (one hash over every case
commitment) is printed before the first agent starts. Only then do the agents run.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import traceback
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from argus.contracts.events import BenchProgressPayload
from bench.agents import Agent, AgentOutput
from bench.claims import claims_from_output
from bench.grade import RunGrade, WorldWindow, grade_run
from bench.scorecard import Scorecard, scenario_rows, summarise
from bench.sealed import Envelope, bench_commitment, canonical_truth, seal, verify
from mockmart.sim import WorldConfig
from mockmart.truth import read_truth
from mockmart.world import generate

BUILT_SCENARIOS: tuple[str, ...] = ("quiet", "s1", "s2", "s3", "s4")
DEFAULT_OUT = Path("runs/bench")
Progress = Callable[[BenchProgressPayload], None]


@dataclass(frozen=True)
class SealedCase:
    case: str
    scenario: str
    seed: int
    dir: Path
    world: Path
    manifest: Path
    truth: Path
    envelope: Envelope


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def prepare_case(scenario: str, seed: int, out_root: Path, case: str | None = None) -> SealedCase:
    """Generate one world and seal its truth. `case` names the directory (blind runs hide the scenario)."""
    case = case or f"{scenario}-{seed}"
    case_dir = out_root / case
    if case_dir.exists():
        shutil.rmtree(case_dir)
    paths = generate(scenario, WorldConfig(seed=seed), case_dir / "world")
    sealed_dir = case_dir / "sealed"
    sealed_dir.mkdir()
    truth = sealed_dir / "truth.duckdb"
    paths.truth.replace(truth)
    envelope = seal(truth)
    (case_dir / "commitment.json").write_text(
        json.dumps({"case": case, "commitment": envelope.commitment, "sealed_at": _now()}, indent=2) + "\n"
    )
    return SealedCase(case, scenario, seed, case_dir, paths.world, paths.manifest, truth, envelope)


def run_agent(case: SealedCase, agent: Agent) -> tuple[AgentOutput, float, str | None]:
    started = time.perf_counter()
    try:
        output = agent.run(case.world, case.manifest)
        error = None
    except Exception as exc:  # an agent crash is a result, not a bench failure
        output, error = AgentOutput(), f"{type(exc).__name__}: {exc}"
        (case.dir / f"{agent.name}.error.txt").write_text(traceback.format_exc())
    seconds = time.perf_counter() - started
    output.write(case.dir / "agents" / agent.name)
    return output, seconds, error


def reveal(case: SealedCase) -> bool:
    """Write the reveal next to the commitment and check that the truth still hashes to it."""
    payload = canonical_truth(case.truth)
    verified = verify(case.envelope.commitment, case.envelope.nonce, payload)
    doc = {**case.envelope.reveal(), "payload": payload, "verified": verified, "revealed_at": _now()}
    (case.dir / "reveal.json").write_text(json.dumps(doc, indent=2) + "\n")
    return verified


def grade_case(
    case: SealedCase, agent: str, output: AgentOutput, seconds: float, verified: bool, error: str | None = None
) -> RunGrade:
    window = WorldWindow.from_manifest(json.loads(case.manifest.read_text()))
    return grade_run(
        read_truth(case.truth),
        claims_from_output(output),
        window,
        case=case.case,
        scenario=case.scenario,
        seed=case.seed,
        agent=agent,
        commitment=case.envelope.commitment,
        verified=verified,
        agent_seconds=seconds,
        error=error,
    )


def git_commit() -> str:
    here = Path(__file__).resolve().parent
    try:
        sha = subprocess.run(
            ["git", "-C", str(here), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(here), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return sha + ("-dirty" if dirty else "")


def run_bench(
    scenarios: Sequence[str],
    seeds: Sequence[int],
    agents: Sequence[Agent],
    out_root: Path,
    *,
    unavailable: dict[str, str] | None = None,
    progress: Progress | None = None,
) -> Scorecard:
    out_root.mkdir(parents=True, exist_ok=True)
    run_id = f"bench-{datetime.now():%Y%m%d-%H%M%S}"
    total = len(scenarios) * len(seeds) * (1 + len(agents)) + 1  # seal each case, commit once, run each agent
    done = 0

    def tick(**last: object) -> None:
        nonlocal done
        done += 1
        if progress is not None:
            progress(BenchProgressPayload(run_id=run_id, done=done, total=total, last=dict(last)))

    # Phase 1: seal. Every truth is fixed and committed before any agent sees any world.
    cases = []
    for scenario in scenarios:
        for seed in seeds:
            case = prepare_case(scenario, seed, out_root)
            cases.append(case)
            tick(phase="sealed", case=case.case, commitment=case.envelope.commitment)
    commitment = bench_commitment({c.case: c.envelope.commitment for c in cases})
    (out_root / "commitment.json").write_text(
        json.dumps(
            {"run_id": run_id, "bench_commitment": commitment, "cases": {c.case: c.envelope.commitment for c in cases}},
            indent=2,
        )
        + "\n"
    )
    tick(phase="committed", bench_commitment=commitment)

    # Phase 2: run. Phase 3: reveal, verify, grade.
    outputs = {}
    for case in cases:
        for agent in agents:
            outputs[(case.case, agent.name)] = run_agent(case, agent)
            tick(phase="ran", case=case.case, agent=agent.name, seconds=round(outputs[(case.case, agent.name)][1], 2))
    grades: list[RunGrade] = []
    for case in cases:
        verified = reveal(case)
        for agent in agents:
            output, seconds, error = outputs[(case.case, agent.name)]
            grades.append(grade_case(case, agent.name, output, seconds, verified, error))
    k = len(seeds)
    card = Scorecard(
        created_at=datetime.now(),
        git_commit=git_commit(),
        bench_commitment=commitment,
        seeds=list(seeds),
        scenarios=list(scenarios),
        agents=[a.name for a in agents],
        unavailable=dict(unavailable or {}),
        summaries=[summarise(a.name, [g for g in grades if g.agent == a.name]) for a in agents],
        rows=[row for a in agents for row in scenario_rows(a.name, [g for g in grades if g.agent == a.name], k)],
        runs=grades,
    )
    (out_root / "scorecard.json").write_text(card.model_dump_json(indent=2) + "\n")
    return card


def load_scorecard(out_root: Path = DEFAULT_OUT) -> Scorecard | None:
    """The latest scorecard under `out_root` (for `GET /bench/results`), or None before the first run."""
    path = out_root / "scorecard.json"
    return Scorecard.model_validate_json(path.read_text()) if path.exists() else None
