"""The simulator's one remediation command changes only the future of the rolled-back budget lines."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import pytest

from argus.contracts.world import ALL_TABLES
from mockmart.remediation import REQUEST_VERSION, RemediationError, RemediationRequest, apply
from mockmart.world import WorldPaths

from .conftest import EFFECTIVE

DECIDED = datetime(2026, 11, 20, 3)


def request(world: Path, out: Path, **overrides: Any) -> dict[str, Any]:
    body = {
        "version": REQUEST_VERSION,
        "action": "rollback_pacer",
        "world": str(world),
        "out": str(out),
        "countries": ["DE", "FR"],
        "to_version": "1.6",
        "effective_at": EFFECTIVE.isoformat(),
        "decided_at": DECIDED.isoformat(),
        "action_id": "act_0001",
        "digest": "sha256:" + "ab" * 32,
    }
    return body | overrides


def differences(a: Path, b: Path) -> dict[str, tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]]:
    """table -> (rows only in a, rows only in b), over every raw table of both worlds."""
    con = duckdb.connect()
    try:
        con.execute(f"ATTACH '{a}' AS a (READ_ONLY)")
        con.execute(f"ATTACH '{b}' AS b (READ_ONLY)")
        out = {}
        for spec in ALL_TABLES:
            name = spec.raw_name
            only_a = con.execute(f"SELECT * FROM a.{name} EXCEPT ALL SELECT * FROM b.{name}").fetchall()
            only_b = con.execute(f"SELECT * FROM b.{name} EXCEPT ALL SELECT * FROM a.{name}").fetchall()
            if only_a or only_b:
                out[name] = (only_a, only_b)
        return out
    finally:
        con.close()


@pytest.fixture(scope="module")
def treated(s4_world: WorldPaths, tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    out = tmp_path_factory.mktemp("treated") / "branch"
    result = apply(RemediationRequest.from_json(request(s4_world.world.parent, out)))
    return out, result


def test_rollback_replaces_only_future_de_fr_ads_rows(s4_world: WorldPaths, treated: tuple[Path, dict]) -> None:
    out, result = treated
    assert not result["noop"]
    assert {line["country"] for line in result["lines"]} == {"DE", "FR"}
    assert {line["from_version"] for line in result["lines"]} == {"1.7"}
    assert result["rows"]["deleted"] == result["rows"]["inserted"] > 0

    diff = differences(s4_world.world, out / "world.duckdb")
    assert set(diff) == {"raw_ads_hourly", "raw_deploys", "raw_ad_budgets"}
    factual_only, treated_only = diff["raw_ads_hourly"]
    for row in factual_only + treated_only:
        ts, _adv, country = row[0], row[1], row[2]
        assert country in ("DE", "FR") and ts >= EFFECTIVE
    for log in ("raw_deploys", "raw_ad_budgets"):
        removed, added = diff[log]
        assert removed == []
        assert added and all(row[1] == EFFECTIVE for row in added)  # (id, ts, ...): logged at the effective hour


def test_every_view_reads_the_same_before_the_effective_hour(s4_world: WorldPaths, treated: tuple[Path, dict]) -> None:
    out, _ = treated
    con = duckdb.connect()
    try:
        con.execute(f"ATTACH '{s4_world.world}' AS a (READ_ONLY)")
        con.execute(f"ATTACH '{out / 'world.duckdb'}' AS b (READ_ONLY)")
        for spec in ALL_TABLES:
            if not spec.batched:
                continue
            sql = "SELECT * FROM {db}." + spec.raw_name + " WHERE ingested_at < TIMESTAMP '2026-11-21 00:00:00'"
            left = sorted(map(repr, con.execute(sql.format(db="a")).fetchall()))
            right = sorted(map(repr, con.execute(sql.format(db="b")).fetchall()))
            assert left == right, spec.name
    finally:
        con.close()


def test_rolled_back_lines_pace_on_plan_again(treated: tuple[Path, dict], s4_world: WorldPaths) -> None:
    out, _ = treated
    sql = (
        "SELECT SUM(s) / SUM(p) FROM (SELECT ts, advertiser_id, country, SUM(ad_spend) AS s FROM fact_ads_hourly "
        "WHERE country IN ('DE', 'FR') AND ts >= TIMESTAMP '2026-11-21 00:00:00' AND ts < TIMESTAMP "
        "'2026-11-21 06:00:00' GROUP BY ALL) JOIN (SELECT ts, advertiser_id, country, planned_spend AS p FROM "
        "fact_ad_plan_hourly) USING (ts, advertiser_id, country)"
    )
    ratios = []
    for world in (s4_world.world, out / "world.duckdb"):
        con = duckdb.connect(str(world), read_only=True)
        con.execute("SET VARIABLE as_of = TIMESTAMP '2026-11-22 00:00:00'")
        ratios.append(float(con.execute(sql).fetchone()[0]))  # type: ignore[index]
        con.close()
    factual, rolled_back = ratios
    assert factual > 2.0  # pacer 1.7 front-loads the day
    assert abs(rolled_back - 1.0) < 0.1


def test_same_request_draws_the_same_future(s4_world: WorldPaths, treated: tuple[Path, dict], tmp_path: Path) -> None:
    out, result = treated
    again = apply(RemediationRequest.from_json(request(s4_world.world.parent, tmp_path / "again")))
    assert again == result
    assert differences(out / "world.duckdb", tmp_path / "again" / "world.duckdb") == {}


def test_lines_already_on_the_base_pacer_are_a_noop(s4_world: WorldPaths, tmp_path: Path) -> None:
    result = apply(RemediationRequest.from_json(request(s4_world.world.parent, tmp_path / "uk", countries=["UK"])))
    assert result["noop"] and result["lines"] == [] and result["rows"] == {"deleted": 0, "inserted": 0}
    assert differences(s4_world.world, tmp_path / "uk" / "world.duckdb") == {}


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"effective_at": "2026-11-21T05:00:00"}, "budget-day boundary"),
        ({"decided_at": "2026-11-21T01:00:00"}, "past cannot change"),
        ({"action": "drop_tables"}, "unknown action"),
        ({"countries": ["DE", "XX"]}, "subset"),
        ({"to_version": "1.5"}, "restores pacer 1.6"),
        ({"digest": "nope"}, "malformed"),
    ],
)
def test_invalid_requests_are_refused(overrides: dict[str, Any], message: str, tmp_path: Path) -> None:
    with pytest.raises(RemediationError, match=message):
        RemediationRequest.from_json(request(tmp_path, tmp_path / "out", **overrides))
    with pytest.raises(RemediationError, match="exactly"):
        RemediationRequest.from_json(request(tmp_path, tmp_path / "out", extra=1))


def test_a_branch_is_not_remediated_again(treated: tuple[Path, dict], tmp_path: Path) -> None:
    out, _ = treated
    with pytest.raises(RemediationError, match="already a remediated branch"):
        apply(RemediationRequest.from_json(request(out, tmp_path / "chain")))


def test_a_world_without_its_configuration_is_refused(s4_world: WorldPaths, tmp_path: Path) -> None:
    bare = tmp_path / "bare"
    bare.mkdir()
    for name in ("world.duckdb", "manifest.json"):
        shutil.copyfile(s4_world.world.parent / name, bare / name)
    with pytest.raises(RemediationError, match="no simulator configuration"):
        apply(RemediationRequest.from_json(request(bare, tmp_path / "out")))


def test_a_world_from_another_seed_is_refused(s4_world: WorldPaths, tmp_path: Path) -> None:
    fake = tmp_path / "fake"
    shutil.copytree(s4_world.world.parent, fake)
    con = duckdb.connect(str(fake / "truth.duckdb"))
    con.execute("UPDATE world_params SET value = '2' WHERE key = 'seed'")
    con.close()
    with pytest.raises(RemediationError, match="does not match"):
        apply(RemediationRequest.from_json(request(fake, tmp_path / "out")))


def test_command_line_reports_refusals_as_json(tmp_path: Path) -> None:
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request(tmp_path, tmp_path / "out", action="drop_tables")))
    done = subprocess.run(
        [sys.executable, "-m", "mockmart.remediation", "apply", "--request", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 2
    assert "unknown action" in json.loads(done.stdout)["error"]
