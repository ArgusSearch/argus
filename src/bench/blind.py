"""Blind challenge: a hidden scenario, the truth committed by hash before Argus runs, then the reveal.

It is the bench with one case and the scenario kept secret: the case directory is named by the seed
only, the world and manifest never name the scenario, and the scenario is drawn with `secrets` unless a
rehearsal forces one. The three C5 `challenge_state` payloads (committed, running, revealed) are
written to `<case>/challenge.jsonl` and passed to `emit`, so the API can stream the same sequence.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from argus.contracts.events import ChallengeStatePayload
from bench.agents import Agent
from bench.claims import Claim, claims_from_output
from bench.grade import RunGrade
from bench.runner import BUILT_SCENARIOS, grade_case, prepare_case, reveal, run_agent

Emit = Callable[[ChallengeStatePayload], None]


@dataclass(frozen=True)
class BlindResult:
    case_dir: Path
    scenario: str
    seed: int
    commitment: str
    claims: list[Claim]
    grade: RunGrade


def blind_challenge(
    agent: Agent,
    out_root: Path,
    *,
    seed: int | None = None,
    scenario: str | None = None,
    menu: Sequence[str] = BUILT_SCENARIOS,
    emit: Emit | None = None,
) -> BlindResult:
    seed = seed if seed is not None else 1000 + secrets.randbelow(9000)
    scenario = scenario or secrets.choice(list(menu))
    case = prepare_case(scenario, seed, out_root, case=f"blind-{seed}")
    log = case.dir / "challenge.jsonl"

    def state(payload: ChallengeStatePayload) -> None:
        with log.open("a") as fh:
            fh.write(payload.model_dump_json() + "\n")
        if emit is not None:
            emit(payload)

    state(ChallengeStatePayload(state="committed", commitment=case.envelope.commitment))
    state(ChallengeStatePayload(state="running", commitment=case.envelope.commitment))
    output, seconds, error = run_agent(case, agent)
    verified = reveal(case)
    grade = grade_case(case, agent.name, output, seconds, verified, error)
    revealed = json.loads((case.dir / "reveal.json").read_text())
    state(
        ChallengeStatePayload(
            state="revealed",
            commitment=case.envelope.commitment,
            reveal={
                "scenario": scenario,
                "seed": seed,
                "nonce": revealed["nonce"],
                "payload": revealed["payload"],
                "verified": verified,
                "grade": grade.model_dump(mode="json"),
            },
        )
    )
    return BlindResult(case.dir, scenario, seed, case.envelope.commitment, claims_from_output(output), grade)
