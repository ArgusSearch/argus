"""End-to-end bench tests: sealing, the agent boundary, grading through real worlds, the CLI and the blind challenge."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from argus.contracts.findings import (
    Cost,
    EvidenceRef,
    Findings,
    Incident,
    IncidentState,
    IncidentTransition,
    Note,
    ObservedChange,
    Quantity,
    RootCause,
    RuledOut,
    Verdict,
    Window,
)
from bench.agents import AgentOutput, AgentUnavailable, resolve_agent
from bench.blind import blind_challenge
from bench.cli import main
from bench.runner import BUILT_SCENARIOS, run_bench
from bench.sealed import canonical_truth, seal
from mockmart.truth import read_truth

pytestmark = pytest.mark.e2e


def _ref(log_id: str, ts: datetime) -> EvidenceRef:
    return EvidenceRef(log="log_events", ref=log_id, ts=ts, kind="x", description=log_id)


def _perfect(truth: list[dict]) -> AgentOutput:
    """What a flawless Argus would say about these truth events (built from the truth, tests only)."""
    q = Quantity(value=1.0, unit="count", receipt=None)
    incidents, notes = [], []
    for i, e in enumerate(t for t in truth if t["kind"] != "red_herring"):
        exp, seen = e["expected"], e["start_ts"] + timedelta(hours=2)
        segment = (exp.get("segments_any") or [exp.get("segment", e["segment"])])[0]
        node = exp.get("root_node") or e["root_node"]
        evidence = exp.get("evidence")
        if e["kind"] == "fault":
            findings = Findings(
                anomaly_id=f"an_{i}",
                verdict=Verdict.SUPPORTED_CAUSE,
                headline="cause found",
                as_of=seen,
                window=Window(start=e["start_ts"], end=e["start_ts"]),
                observed=ObservedChange(node=node, segment=segment, observed=q, expected=q, change_pct=q),
                root=RootCause(
                    node=node, segment=segment, direction="down", evidence=_ref(evidence, seen), change_pct=q
                ),
                ruled_out=[
                    RuledOut(hypothesis=r, prediction="p", result="refuted", reason="holdout", evidence=_ref(r, seen))
                    for r in exp.get("ruled_out", [])
                ],
                explained_share=1.0,
                unexplained_share=0.0,
                cost=Cost(queries=1, seconds=0.1),
            )
            incidents.append(
                Incident(
                    id=f"INC-{i}",
                    fingerprint="f",
                    title="t",
                    verdict=Verdict.SUPPORTED_CAUSE,
                    state=IncidentState.EXPLAINED,
                    root_node=node,
                    segment=segment,
                    direction="down",
                    severity_eur=1.0,
                    opened_at=e["start_ts"],
                    updated_at=seen,
                    history=[IncidentTransition(sim_ts=seen, from_state=None, to_state=IncidentState.OPEN, reason="")],
                    findings=findings,
                )
            )
        else:
            kind = "expected" if e["kind"] == "innocent" else "data_issue"
            notes.append(Note(id=f"note_{i}", kind=kind, sim_ts=seen, node=node, segment=segment, reason=f"{evidence}"))
    return AgentOutput(incidents=incidents, notes=notes)


class OracleAgent:
    """Cheats on purpose (reads the sealed truth) to prove that a perfect answer grades 4 everywhere.

    It also asserts the boundary the real agents rely on: the commitment exists before it runs, and the
    world directory it is handed holds no truth file.
    """

    name = "oracle"

    def run(self, world: Path, manifest: Path) -> AgentOutput:
        case_dir = world.parent.parent
        assert (case_dir / "commitment.json").exists(), "commitment must be written before the agent runs"
        assert not (case_dir / "reveal.json").exists(), "nothing is revealed while agents run"
        assert sorted(p.name for p in world.parent.iterdir()) == ["manifest.json", "world.duckdb"]
        assert "truth" not in manifest.read_text()
        return _perfect(read_truth(case_dir / "sealed" / "truth.duckdb"))


def fixture_agent(world: Path) -> dict:
    """A `module:function` agent that returns plain JSON, as an out-of-tree runtime might."""
    return {"notes": [{"id": "n1", "kind": "expected", "sim_ts": "2026-11-20T10:00:00", "reason": "quiet"}]}


def test_oracle_scores_perfect_and_threshold_is_graded(tmp_path: Path):
    card = run_bench(BUILT_SCENARIOS, [1], [OracleAgent(), resolve_agent("threshold")], tmp_path)
    oracle, threshold = card.summaries
    assert oracle.agent == "oracle" and oracle.pass_at_1 == 1.0 and oracle.mean_grade == 4.0
    assert oracle.recall == 1.0 and oracle.cause_accuracy == 1.0 and oracle.precision == 1.0
    assert oracle.false_alarms == 0 and oracle.innocent_handled == 1 and oracle.data_handled == 1
    assert oracle.all_verified and threshold.all_verified
    assert threshold.cause_accuracy == 0.0, "a threshold alert never names a cause"
    s3 = next(r for r in card.runs if r.agent == "threshold" and r.scenario == "s3")
    assert s3.events[0].grade == 0 and s3.false_alarms, "the baseline pages on a data stall"
    saved = json.loads((tmp_path / "scorecard.json").read_text())
    assert saved["bench_commitment"] == card.bench_commitment and len(saved["runs"]) == 2 * len(BUILT_SCENARIOS)
    commit = json.loads((tmp_path / "commitment.json").read_text())
    assert set(commit["cases"]) == {f"{s}-1" for s in BUILT_SCENARIOS}


def test_seal_is_reproducible_and_tamper_evident(world):
    paths = world("s1", 1)
    envelope = seal(paths.truth, nonce="n")
    assert seal(paths.truth, nonce="n") == envelope
    assert json.loads(envelope.payload)["world_params"]["scenario"] == "s1"
    assert canonical_truth(paths.truth) == envelope.payload


def test_cli_run_case_blind_verify(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    out = tmp_path / "bench"
    assert main(["run", "--scenarios", "quiet", "--runs", "1", "--agents", "threshold", "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "bench commitment" in text and "threshold" in text and (out / "scorecard.json").exists()

    record = tmp_path / "rec"
    assert main(["s3", "--seed", "2", "--agents", "threshold", "--out", str(out), "--record", str(record)]) == 0
    assert {"incidents.json", "notes.json", "findings.json", "grade.json", "reveal.json"} <= {
        p.name for p in record.iterdir()
    }
    assert "paged a business incident" in capsys.readouterr().out

    assert main(["blind", "--seed", "11", "--scenario", "s2", "--agents", "threshold", "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert text.index("commitment:") < text.index("reveal: scenario s2")
    case = out / "blind-11"
    states = [json.loads(line)["state"] for line in (case / "challenge.jsonl").read_text().splitlines()]
    assert states == ["committed", "running", "revealed"]
    assert main(["verify", str(case)]) == 0

    reveal = json.loads((case / "reveal.json").read_text())
    reveal["payload"] = reveal["payload"].replace('"s2"', '"s1"')
    (case / "reveal.json").write_text(json.dumps(reveal))
    assert main(["verify", str(case)]) == 1, "a swapped truth no longer matches the commitment"


def test_blind_hides_the_scenario_until_reveal(tmp_path: Path):
    seen: list[str] = []
    result = blind_challenge(
        resolve_agent("threshold"), tmp_path, seed=5, menu=["s1", "s4"], emit=lambda p: seen.append(p.state)
    )
    assert result.scenario in {"s1", "s4"} and result.case_dir.name == "blind-5"
    assert seen == ["committed", "running", "revealed"] and result.grade.verified
    world_files = " ".join(p.name for p in (result.case_dir / "world").iterdir())
    assert result.scenario not in world_files


def test_unavailable_agents_are_reported(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ARGUS_BENCH_AGENT", "argus.no_such_runtime:run_world")
    with pytest.raises(AgentUnavailable):
        resolve_agent("argus")
    with pytest.raises(AgentUnavailable):
        resolve_agent("bench.sealed:no_such_fn")
    with pytest.raises(SystemExit, match="cannot record"):
        main(["case", "s1", "--record", "unused-dir"])  # fixtures must never come from a fallback agent


def test_callable_and_command_agents(tmp_path: Path, world):
    paths = world("quiet", 1)
    py = resolve_agent("test_bench_runner:fixture_agent")
    assert py.run(paths.world, paths.manifest).notes[0].id == "n1"
    script = tmp_path / "agent.py"
    script.write_text(
        "import json, sys\n"
        "out = sys.argv[sys.argv.index('--out') + 1]\n"
        "note = {'id': 'n1', 'kind': 'expected', 'sim_ts': '2026-11-20T10:00:00', 'reason': 'quiet'}\n"
        "open(out + '/notes.json', 'w').write(json.dumps([note]))\n"
    )
    cmd = resolve_agent(f"cmd:{sys.executable} {script} --world {{world}} --manifest {{manifest}} --out {{out}}")
    assert cmd.run(paths.world, paths.manifest).notes[0].reason == "quiet"
