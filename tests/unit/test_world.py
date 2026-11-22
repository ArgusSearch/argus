"""MockMart world: identities by construction, as_of delivery, completeness, hidden truth."""

from __future__ import annotations

import ast
import json
import math
from datetime import datetime, timedelta
from fractions import Fraction
from pathlib import Path

import duckdb
import numpy as np

from argus.contracts.world import ALL_TABLES
from mockmart.truth import read_truth
from mockmart.world import WorldPaths


def _con(paths: WorldPaths, as_of: datetime) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(paths.world), read_only=True)
    con.execute(f"SET VARIABLE as_of = TIMESTAMP '{as_of:%Y-%m-%d %H:%M:%S}'")
    return con


def test_orders_equal_payment_successes_in_every_segment_hour(s1_world: WorldPaths) -> None:
    con = _con(s1_world, datetime(2026, 12, 1))
    mismatches = con.execute(
        """SELECT COUNT(*) FROM
           (SELECT ts, country, platform, SUM(orders) o FROM fact_orders_hourly GROUP BY ALL) o
           JOIN (SELECT ts, country, platform, SUM(payment_successes) p FROM fact_payments_hourly GROUP BY ALL) p
           USING (ts, country, platform) WHERE o <> p"""
    ).fetchone()
    assert mismatches == (0,)


def test_as_of_shows_only_delivered_batches(s1_world: WorldPaths) -> None:
    manifest = json.loads(s1_world.manifest.read_text())
    hour = datetime.fromisoformat(manifest["live_start"]) + timedelta(hours=10)
    q = f"SELECT SUM(share) FROM log_ingestion WHERE table_name = 'fact_orders_hourly' AND ts = TIMESTAMP '{hour}'"
    early = _con(s1_world, hour + timedelta(hours=1, minutes=10)).execute(q).fetchone()
    late = _con(s1_world, hour + timedelta(hours=2)).execute(q).fetchone()
    assert early is not None and late is not None
    assert early[0] == 0.55 and abs(late[0] - 1.0) < 1e-9
    n = f"SELECT SUM(orders) FROM fact_orders_hourly WHERE ts = TIMESTAMP '{hour}'"
    partial = _con(s1_world, hour + timedelta(hours=1, minutes=10)).execute(n).fetchone()
    full = _con(s1_world, hour + timedelta(hours=2)).execute(n).fetchone()
    assert partial is not None and full is not None and partial[0] < full[0]


def test_logs_are_invisible_before_they_happen(s1_world: WorldPaths) -> None:
    fault = next(e for e in read_truth(s1_world.truth) if e["kind"] == "fault")
    q = "SELECT COUNT(*) FROM log_deploys WHERE id = 'dep_android-app_8.3.0'"
    before = _con(s1_world, fault["start_ts"] - timedelta(hours=1)).execute(q).fetchone()
    after = _con(s1_world, fault["start_ts"] + timedelta(hours=1)).execute(q).fetchone()
    assert before == (0,) and after == (1,)


def test_s1_signature_is_planted(s1_world: WorldPaths) -> None:
    fault = next(e for e in read_truth(s1_world.truth) if e["kind"] == "fault")
    t0 = fault["start_ts"]
    con = _con(s1_world, datetime(2026, 12, 1))
    rows = dict(
        con.execute(
            f"""SELECT provider, SUM(payment_successes) / SUM(payment_attempts) FROM fact_payments_hourly
                WHERE country = 'DE' AND platform = 'android' AND ts = TIMESTAMP '{t0}' GROUP BY provider"""
        ).fetchall()
    )
    assert rows["PayCo"] < 0.8 and rows["CardHub"] > 0.9 and rows["WalletGo"] > 0.9
    other = con.execute(
        f"""SELECT SUM(payment_successes) / SUM(payment_attempts) FROM fact_payments_hourly
            WHERE country <> 'DE' AND platform = 'android' AND ts = TIMESTAMP '{t0}'"""
    ).fetchone()
    assert other is not None and other[0] > 0.9


def test_manifest_never_names_the_scenario(s1_world: WorldPaths) -> None:
    text = s1_world.manifest.read_text().lower()
    assert "s1" not in text and "payco" not in text and "scenario" not in text


def test_same_seed_same_world(tmp_path: Path) -> None:
    """Two generations with the same seed are identical row by row, in every world and truth table.

    Compares contents, not float aggregates: DuckDB sums DOUBLE values in a layout- and thread-dependent order,
    which made an earlier version of this test flaky in the last bits (money is now DECIMAL, see C1).
    """
    from mockmart.sim import WorldConfig
    from mockmart.world import generate

    cfg = WorldConfig(seed=11, days=40, live_days=4)
    a, b = generate("s1", cfg, tmp_path / "a"), generate("s1", cfg, tmp_path / "b")
    con = duckdb.connect()
    for alias, paths in (("wa", a), ("wb", b)):
        con.execute(f"ATTACH '{paths.world}' AS {alias} (READ_ONLY)")
        con.execute(f"ATTACH '{paths.truth}' AS t{alias} (READ_ONLY)")
    pairs = [(f"wa.{t.raw_name}", f"wb.{t.raw_name}") for t in ALL_TABLES]
    pairs += [(f"twa.{t}", f"twb.{t}") for t in ("injected_events", "world_params")]
    for left, right in pairs:
        rows = con.execute(f"SELECT COUNT(*) FROM {left}").fetchone()
        diff = con.execute(
            f"SELECT (SELECT COUNT(*) FROM (SELECT * FROM {left} EXCEPT ALL SELECT * FROM {right})) "
            f"+ (SELECT COUNT(*) FROM (SELECT * FROM {right} EXCEPT ALL SELECT * FROM {left}))"
        ).fetchone()
        assert diff == (0,), f"{left} differs from {right} in {diff} rows (of {rows})"
    assert (
        con.execute("SELECT SUM(gmv) FROM wa.raw_orders_hourly").fetchone()
        == con.execute("SELECT SUM(gmv) FROM wb.raw_orders_hourly").fetchone()
    ), "money sums must be exact"
    manifest_a, manifest_b = (json.loads(p.manifest.read_text()) for p in (a, b))
    manifest_a.pop("seconds"), manifest_b.pop("seconds")
    assert manifest_a == manifest_b


def test_binomial_draws_do_not_depend_on_fused_multiply_add() -> None:
    """The same seed draws the same world on every platform, not only twice on one machine.

    numpy's binomial sampler puts its mode at floor(n * p + p). The macOS arm64 numpy wheels fuse that
    multiply-add (one rounding of the exact value), the Linux wheels round the product first. For the
    cart rate 0.24 and n = 374 that is mode 90 on a Mac and 89 on CI, so CI generated a different world
    and every recorded hash and event count disagreed. MockMart puts p on a 2**-30 grid, where
    n * p + p is exact, so fused and unfused arithmetic agree.
    """
    from mockmart.sim import MAX_BINOMIAL_N, on_p_grid

    def fused(n: int, p: float) -> float:
        return float((n + 1) * Fraction(p))

    assert math.floor(374 * 0.24 + 0.24) == 89 and math.floor(fused(374, 0.24)) == 90

    rng = np.random.default_rng(0)
    rates = [0.24, 0.264, 0.252, 0.132, 0.62, 0.52, 0.9, 0.95, 0.94, 0.5, 0.6, 0.55, 0.25 / 0.45, 0.15 / 0.2]
    rates += [0.021, 0.025, 0.015, 0.017, 0.023, 0.014, 0.035, 0.03, 0.045, 0.04, 0.032, 0.05]
    rates += rng.uniform(0, 1, 50).tolist()
    counts = [*range(3000), *range(MAX_BINOMIAL_N - 100, MAX_BINOMIAL_N)]
    for rate in rates:
        grid = float(on_p_grid(rate))
        assert abs(grid - rate) < 1e-9
        for r in (grid, 1.0 - grid):  # numpy samples with min(p, 1 - p)
            bad = [n for n in counts if n * r + r != fused(n, r)]
            assert not bad, f"p={rate}: n * p + p is inexact for n in {bad[:5]}"


def test_mockmart_draws_every_binomial_through_the_platform_safe_helper() -> None:
    src = Path(__file__).resolve().parents[2] / "src" / "mockmart"
    direct = []
    for path in src.rglob("*.py"):
        tree = ast.parse(path.read_text())
        helper = {
            id(node)
            for fn in ast.walk(tree)
            if isinstance(fn, ast.FunctionDef) and fn.name == "binomial" and path.name == "sim.py"
            for node in ast.walk(fn)
        }
        direct += [
            f"{path.relative_to(src)}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "binomial"
            and id(node) not in helper
        ]
    assert not direct, f"use mockmart.sim.binomial, not rng.binomial: {direct}"
