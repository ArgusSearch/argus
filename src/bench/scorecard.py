"""Aggregate graded runs into the scorecard: one summary per agent, one row per agent and scenario.

| measure              | meaning                                                                  |
|----------------------|--------------------------------------------------------------------------|
| recall               | faults detected (any page that touches them) / faults injected           |
| cause accuracy       | faults graded 3 or 4 (supported cause matches the truth) / faults        |
| time to detect       | sim hours from fault start to the first page, median and max             |
| precision            | pages that touch a fault / all pages                                     |
| false alarms per day | pages that touch no fault / live days; also on quiet worlds alone        |
| expected handled     | innocent changes explained without a page (grade 3+) / innocent changes  |
| data issues          | data faults labelled DATA_ISSUE with no page / data faults; and precision |
| pass@1, pass^k       | share of runs that pass; chance that k runs of a scenario all pass       |
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime
from itertools import groupby

from pydantic import BaseModel, ConfigDict, Field

from bench.grade import PASS_GRADE, RunGrade


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def pass_hat_k(n: int, c: int, k: int) -> float:
    """Unbiased estimate of P(k independent runs all pass) from c passes in n runs (tau-bench)."""
    if k > n:
        raise ValueError("k must not exceed the number of runs")
    return math.comb(c, k) / math.comb(n, k)


class ScenarioRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str
    scenario: str
    runs: int
    passed: int
    pass_at_1: float
    k: int
    pass_hat_k: float
    mean_grade: float | None
    ttd_median_h: float | None
    false_alarms: int
    verdicts: list[str] = Field(description="'label' of each run's first graded event, in seed order")


class AgentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str
    runs: int
    live_days: float
    faults: int
    detected: int
    recall: float | None
    cause_correct: int
    cause_accuracy: float | None
    exact: int
    ttd_median_h: float | None
    ttd_max_h: float | None
    pages: int
    true_pages: int
    precision: float | None
    false_alarms: int
    false_alarms_per_day: float | None
    quiet_false_alarms_per_day: float | None
    innocent: int
    innocent_handled: int
    data_faults: int
    data_handled: int
    data_claims: int
    data_precision: float | None
    mean_grade: float | None
    pass_at_1: float | None
    all_verified: bool
    agent_seconds: float


class Scorecard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_at: datetime
    git_commit: str
    bench_commitment: str = Field(description="hash over every case commitment, printed before any agent ran")
    seeds: list[int]
    scenarios: list[str]
    agents: list[str]
    unavailable: dict[str, str] = Field(default_factory=dict, description="agent -> why it did not run")
    summaries: list[AgentSummary]
    rows: list[ScenarioRow]
    runs: list[RunGrade]


def summarise(agent: str, runs: list[RunGrade]) -> AgentSummary:
    events = [e for r in runs for e in r.events]
    faults = [e for e in events if e.kind == "fault"]
    innocent = [e for e in events if e.kind == "innocent"]
    data = [e for e in events if e.kind == "data"]
    ttd = [e.ttd_hours for e in faults if e.grade >= 1 and e.ttd_hours is not None]
    pages = sum(r.pages for r in runs)
    false_alarms = sum(len(r.false_alarms) for r in runs)
    quiet = [r for r in runs if r.scenario == "quiet"]
    live_days = sum(r.live_days for r in runs)
    quiet_days = sum(r.live_days for r in quiet)
    return AgentSummary(
        agent=agent,
        runs=len(runs),
        live_days=live_days,
        faults=len(faults),
        detected=sum(e.grade >= 1 for e in faults),
        recall=_ratio(sum(e.grade >= 1 for e in faults), len(faults)),
        cause_correct=sum(e.grade >= PASS_GRADE for e in faults),
        cause_accuracy=_ratio(sum(e.grade >= PASS_GRADE for e in faults), len(faults)),
        exact=sum(e.grade == 4 for e in faults),
        ttd_median_h=round(statistics.median(ttd), 2) if ttd else None,
        ttd_max_h=max(ttd) if ttd else None,
        pages=pages,
        true_pages=pages - false_alarms,
        precision=_ratio(pages - false_alarms, pages),
        false_alarms=false_alarms,
        false_alarms_per_day=round(false_alarms / live_days, 3) if live_days else None,
        quiet_false_alarms_per_day=(
            round(sum(len(r.false_alarms) for r in quiet) / quiet_days, 3) if quiet_days else None
        ),
        innocent=len(innocent),
        innocent_handled=sum(e.passed for e in innocent),
        data_faults=len(data),
        data_handled=sum(e.passed for e in data),
        data_claims=sum(r.data_claims for r in runs),
        data_precision=_ratio(sum(r.true_data_claims for r in runs), sum(r.data_claims for r in runs)),
        mean_grade=round(statistics.mean(e.grade for e in events), 2) if events else None,
        pass_at_1=_ratio(sum(r.passed for r in runs), len(runs)),
        all_verified=all(r.verified for r in runs),
        agent_seconds=round(sum(r.agent_seconds for r in runs), 1),
    )


def scenario_rows(agent: str, runs: list[RunGrade], k: int) -> list[ScenarioRow]:
    rows = []
    for scenario in dict.fromkeys(r.scenario for r in runs):
        mine = sorted((r for r in runs if r.scenario == scenario), key=lambda r: r.seed)
        grades = [e.grade for r in mine for e in r.events]
        ttd = [e.ttd_hours for r in mine for e in r.events if e.kind == "fault" and e.ttd_hours is not None]
        passed = sum(r.passed for r in mine)
        kk = min(k, len(mine))
        rows.append(
            ScenarioRow(
                agent=agent,
                scenario=scenario,
                runs=len(mine),
                passed=passed,
                pass_at_1=round(passed / len(mine), 3),
                k=kk,
                pass_hat_k=round(pass_hat_k(len(mine), passed, kk), 3),
                mean_grade=round(statistics.mean(grades), 2) if grades else None,
                ttd_median_h=round(statistics.median(ttd), 2) if ttd else None,
                false_alarms=sum(len(r.false_alarms) for r in mine),
                verdicts=[(r.events[0].label if r.events else ("pass" if r.passed else "false alarm")) for r in mine],
            )
        )
    return rows


def _fmt(value: float | None, pct: bool = False) -> str:
    if value is None:
        return "-"
    return f"{value:.0%}" if pct else f"{value:g}"


def _labels(labels: list[str]) -> str:
    """'exact | exact | silent' -> '2x exact | silent' (runs in seed order, repeats folded)."""
    parts = []
    for label, group in groupby(labels):
        n = len(list(group))
        parts.append(f"{n}x {label}" if n > 1 else label)
    return " | ".join(parts)


def render(card: Scorecard) -> str:
    """Plain-text scorecard for the terminal."""
    out = [
        f"Argus bench  {card.created_at:%Y-%m-%d %H:%M}  commit {card.git_commit}",
        f"bench commitment (sealed before any agent ran): {card.bench_commitment}",
        f"scenarios {', '.join(card.scenarios)}  seeds {', '.join(map(str, card.seeds))}",
    ]
    for agent, why in card.unavailable.items():
        out.append(f"agent {agent}: not run ({why})")
    out.append("")
    header = (
        f"{'agent':<10} {'recall':>6} {'cause':>6} {'exact':>6} {'TTD h':>9} {'prec':>5} {'FA/day':>7} "
        f"{'quietFA':>7} {'expect':>6} {'data':>6} {'grade':>5} {'pass@1':>6} {'truth':>5}"
    )
    out += [header, "-" * len(header)]
    for s in card.summaries:
        ttd = f"{_fmt(s.ttd_median_h)}/{_fmt(s.ttd_max_h)}"
        out.append(
            f"{s.agent:<10} {_fmt(s.recall, True):>6} {_fmt(s.cause_accuracy, True):>6} "
            f"{_fmt(_ratio(s.exact, s.faults), True):>6} {ttd:>9} {_fmt(s.precision, True):>5} "
            f"{_fmt(s.false_alarms_per_day):>7} {_fmt(s.quiet_false_alarms_per_day):>7} "
            f"{_fmt(_ratio(s.innocent_handled, s.innocent), True):>6} "
            f"{_fmt(_ratio(s.data_handled, s.data_faults), True):>6} "
            f"{_fmt(s.mean_grade):>5} {_fmt(s.pass_at_1, True):>6} {'ok' if s.all_verified else 'FAIL':>5}"
        )
    out += ["", f"{'agent':<10} {'scenario':<8} {'pass@1':>6} {'pass^k':>8} {'grade':>5} {'TTD h':>6} {'FA':>3}  runs"]
    for r in card.rows:
        pk = f"{_fmt(r.pass_hat_k, True)} k={r.k}"
        out.append(
            f"{r.agent:<10} {r.scenario:<8} {_fmt(r.pass_at_1, True):>6} {pk:>8} {_fmt(r.mean_grade):>5} "
            f"{_fmt(r.ttd_median_h):>6} {r.false_alarms:>3}  {_labels(r.verdicts)}"
        )
    out += [
        "",
        "recall/cause/exact: faults detected / right cause (grade 3+) / exact (grade 4).  TTD: median/max sim hours.",
        "prec: pages that touch a fault.  FA/day: pages touching no fault per live day (quietFA: quiet worlds only).",
        "expect: planned changes explained without a page.  data: data faults labelled DATA_ISSUE without a page.",
        "grade: mean 0..4 over graded events (confident wrong = 0).  truth: every revealed truth matched its hash.",
    ]
    return "\n".join(out)
