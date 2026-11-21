"""MockMart world: identities by construction, as_of delivery, completeness, hidden truth."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import duckdb

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
