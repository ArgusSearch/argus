"""Judge an applied rollback against its untouched twin, from receipted queries on both worlds.

The rule is fixed before approval (`SuccessRule`): over the first `hours` complete hours from the effective
hour, the treated scope's pacing ratio (ratio of sums, spend / planned spend) must be within 0.15 of 1 in
every hour, and its aggregate gap from 1 must be at most half the untreated twin's over the same hours. The
untreated gap must be material (0.20 or more) or there is nothing to remove, and the rows outside the scope
must be identical in both worlds or the two are not comparable. A treated series identical to the untreated
one is NO_EFFECT: the action changed nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from argus.agent.types import SuccessRule
from argus.contracts.findings import Receipt
from argus.contracts.world import COUNTRIES
from argus.semantic.compile import quote
from argus.semantic.runner import Runner, sql_ts
from argus.watcher.freshness import COMPLETE, completeness

HOUR = timedelta(hours=1)
HOURS = 3
HOUR_TOLERANCE = 0.15
GAP_FACTOR = 0.5
MATERIAL_GAP = 0.20
ADS_TABLES = ["fact_ad_plan_hourly", "fact_ads_hourly"]


def success_rule(countries: list[str]) -> SuccessRule:
    return SuccessRule(
        node="pacing_ratio",
        scope={"country": list(countries)},
        rule=(
            f"|ratio - 1| <= {HOUR_TOLERANCE} in each of {HOURS} complete hours from the effective hour, and the "
            f"gap at most {GAP_FACTOR:g}x the untreated twin's (untreated gap >= {MATERIAL_GAP}); rows outside "
            "the scope identical in both worlds; the incident resolves"
        ),
        hours=HOURS,
        comparator="untreated_twin",
    )


def pacing_sql(countries: list[str], start: datetime, end: datetime) -> str:
    """Hourly spend and planned spend of the budget lines in `countries`, hours [start, end)."""
    names = ", ".join(quote(c) for c in sorted(countries))
    where = f"ts >= {sql_ts(start)} AND ts < {sql_ts(end)} AND country IN ({names})"
    return (
        "WITH spend AS (SELECT ts, advertiser_id, country, SUM(ad_spend) AS spend FROM fact_ads_hourly "
        f"WHERE {where} GROUP BY ts, advertiser_id, country), "
        f"plan AS (SELECT ts, advertiser_id, country, planned_spend FROM fact_ad_plan_hourly WHERE {where}) "
        "SELECT plan.ts, ROUND(SUM(COALESCE(spend.spend, 0)), 2) AS spend, "
        "ROUND(SUM(plan.planned_spend), 2) AS planned "
        "FROM plan LEFT JOIN spend USING (ts, advertiser_id, country) GROUP BY plan.ts ORDER BY plan.ts"
    )


def control_sql(countries: list[str], start: datetime, end: datetime) -> str:
    """Every ads row outside the treated scope, hours [start, end): must be identical in both worlds."""
    names = ", ".join(quote(c) for c in sorted(countries))
    return (
        "SELECT ts, advertiser_id, country, platform, ad_impressions, ad_clicks, ad_spend, ad_conversions, "
        f"attributed_gmv FROM fact_ads_hourly WHERE ts >= {sql_ts(start)} AND ts < {sql_ts(end)} "
        f"AND country NOT IN ({names}) ORDER BY ts, advertiser_id, country, platform"
    )


def control_countries(countries: list[str]) -> list[str]:
    return [c for c in COUNTRIES if c not in countries]


@dataclass(frozen=True)
class Series:
    receipt: Receipt
    ratios: list[float]
    spend: float
    planned: float

    @property
    def aggregate(self) -> float:
        return self.spend / self.planned


@dataclass(frozen=True)
class Verdict:
    state: str  # VERIFIED (contrast only; the lifecycle is checked by the service), NO_EFFECT, INCONCLUSIVE
    summary: str
    treated: Series | None = None
    untreated: Series | None = None
    controls: tuple[Receipt, Receipt] | None = None


def complete(runner: Runner, start: datetime, hours: int, as_of: datetime) -> bool:
    found = completeness(runner, ADS_TABLES, start, start + (hours - 1) * HOUR, as_of)
    return all(found.get((t, start + k * HOUR), 0.0) >= COMPLETE for t in ADS_TABLES for k in range(hours))


def _series(runner: Runner, countries: list[str], start: datetime, hours: int, as_of: datetime, label: str) -> Series:
    rows, receipt = runner.query(
        pacing_sql(countries, start, start + hours * HOUR), as_of, purpose=f"pacing ratio {label}"
    )
    planned = [float(r["planned"] or 0) for r in rows]
    spend = [float(r["spend"] or 0) for r in rows]
    ratios = [s / p if p else float("nan") for s, p in zip(spend, planned, strict=True)]
    return Series(receipt, ratios, sum(spend), sum(planned))


def judge(
    treated: Runner, untreated: Runner, countries: list[str], effective_at: datetime, as_of: datetime
) -> Verdict | None:
    """None while the measured hours are still arriving; otherwise the contrast verdict with its receipts."""
    if not (complete(treated, effective_at, HOURS, as_of) and complete(untreated, effective_at, HOURS, as_of)):
        return None
    t = _series(treated, countries, effective_at, HOURS, as_of, "treated")
    u = _series(untreated, countries, effective_at, HOURS, as_of, "untreated twin")
    end = effective_at + HOURS * HOUR
    others = control_countries(countries)
    _, control_t = treated.query(control_sql(countries, effective_at, end), as_of, purpose="control rows treated")
    _, control_u = untreated.query(control_sql(countries, effective_at, end), as_of, purpose="control rows twin")

    def verdict(state: str, summary: str) -> Verdict:
        return Verdict(state, summary, t, u, (control_t, control_u))

    if len(t.ratios) != HOURS or len(u.ratios) != HOURS or not t.planned or not u.planned:
        return verdict("INCONCLUSIVE", "the measured hours have no planned spend to compare against")
    if any(r != r for r in t.ratios + u.ratios):  # NaN: an hour without planned spend
        return verdict("INCONCLUSIVE", "an hour in the window has no planned spend")
    if others and control_t.result_hash != control_u.result_hash:
        return verdict("INCONCLUSIVE", f"the {'/'.join(others)} rows differ between the worlds; they are not twins")
    if t.receipt.result_hash == u.receipt.result_hash:
        return verdict("NO_EFFECT", "the treated world equals the untreated twin: the action changed nothing")
    gap_t, gap_u = abs(t.aggregate - 1), abs(u.aggregate - 1)
    if gap_u < MATERIAL_GAP:
        return verdict("INCONCLUSIVE", "the untreated twin has no material pacing gap to remove")
    if max(abs(r - 1) for r in t.ratios) <= HOUR_TOLERANCE and gap_t <= GAP_FACTOR * gap_u:
        return verdict("VERIFIED", "pacing back on plan in every measured hour, against the untreated twin")
    return verdict("NO_EFFECT", "pacing stayed off plan after the action")
