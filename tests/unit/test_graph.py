"""Seed graph and edge tests."""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path

import duckdb

from argus.contracts.graph import EdgeKind, EdgeStatus, Graph
from argus.graph.edge_tests import EdgeTester, eval_expr
from argus.graph.store import Changelog, product_factors
from argus.semantic.runner import Runner
from mockmart.world import WorldPaths


def test_seed_graph_shape(graph: Graph) -> None:
    kinds = {k: sum(e.kind is k for e in graph.edges) for k in EdgeKind}
    assert all(kinds[k] for k in EdgeKind), kinds
    assert {"orders", "gmv", "payment_success_rate", "ad_spend", "cpa"} <= {n.id for n in graph.north_stars()}
    assert all(e.test is not None for e in graph.edges), "every edge carries a test"


def test_product_formulas_flatten_for_lmdi(graph: Graph) -> None:
    assert product_factors(graph, "orders") == [
        "sessions",
        "view_rate",
        "cart_rate",
        "checkout_rate",
        "attempt_rate",
        "payment_success_rate",
    ]
    assert product_factors(graph, "ad_spend") == ["sessions", "impressions_per_session", "ctr", "cpc"]
    assert product_factors(graph, "payment_success_rate") is None


def test_eval_expr_is_restricted() -> None:
    import numpy as np
    import pytest

    assert eval_expr("a * (b + 1) / 2", {"a": np.array(2.0), "b": np.array(3.0)}) == 4.0
    with pytest.raises(ValueError):
        eval_expr("__import__('os')", {})


def test_all_seed_edges_pass_on_a_clean_world(graph: Graph, s1_world: WorldPaths) -> None:
    runner = Runner(s1_world.world)
    tester = EdgeTester(graph, runner)
    changes = tester.run_all(datetime(2026, 11, 18, 2), Changelog())
    tested = [c for c in changes if c.edge.kind in (EdgeKind.FORMULA, EdgeKind.BREAKDOWN)]
    assert tested and all(c.new is EdgeStatus.VALID for c in tested)


def test_a_stalled_table_breaks_the_identity(graph: Graph, s1_world: WorldPaths, tmp_path: Path) -> None:
    """Drop the late batches of fact_orders_hourly for three days: orders = payment_successes must go BROKEN."""
    world = tmp_path / "world.duckdb"
    shutil.copy(s1_world.world, world)
    end = datetime(2026, 11, 21)
    con = duckdb.connect(str(world))
    con.execute(f"DELETE FROM raw_orders_hourly WHERE batch >= 1 AND ts >= TIMESTAMP '{end - timedelta(days=3)}'")
    con.close()
    tester = EdgeTester(graph, Runner(world))
    log = Changelog()
    changes = {c.edge.id: c for c in tester.run_all(end, log)}
    assert changes["f_orders_payments"].new is EdgeStatus.BROKEN
    assert any(c.edge == "f_orders_payments" and c.new_status is EdgeStatus.BROKEN for c in log.entries)
