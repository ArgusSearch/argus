"""Attention budget over the seed graph."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from argus.contracts.graph import EdgeStatus, Graph
from argus.detect.attention import AttentionBudget, Unit, candidate_units

HOUR = datetime(2026, 11, 20, 12)


def scores(budget: AttentionBudget, z_now: dict[str, float], open_nodes: set[str] | None = None) -> dict:
    return {u: budget.terms(u, HOUR, z_now, 1.0, open_nodes or set()) for u in budget.units}


def test_units_are_totals_and_trusted_breakdowns(graph: Graph) -> None:
    units = candidate_units(graph)
    keys = {u.key for u in units}
    assert {"payment_success_rate", "payment_success_rate[provider]", "ad_spend[advertiser_id]"} <= keys
    assert len(keys) == len(units)
    assert all(u.is_total or len(u.dims) == 1 for u in units)


def test_business_weight_follows_the_graph(graph: Graph) -> None:
    budget = AttentionBudget(graph)
    assert budget.weight("payment_success_rate") == 1.0  # north star
    assert budget.weight("payment_successes") == 0.7  # numerator of a north star
    assert budget.weight("view_rate") == 0.7  # formula source of cvr
    assert budget.weight("planned_spend") == 0.5


def test_a_moving_north_star_pulls_attention_onto_its_breakdowns(graph: Graph) -> None:
    budget = AttentionBudget(graph, budget=3)
    chosen = budget.choose(scores(budget, {"payment_success_rate": 9.0}))
    assert chosen and all(u.node == "payment_success_rate" and not u.is_total for u in chosen)
    assert {u.dims[0] for u in chosen} == {"country", "platform", "provider"}


def test_surprise_flows_from_a_ratio_to_its_parts(graph: Graph) -> None:
    budget = AttentionBudget(graph)
    quiet = budget.terms(Unit("payment_successes"), HOUR, {}, 1.0, set())
    moved = budget.terms(Unit("payment_successes"), HOUR, {"payment_success_rate": 5.0}, 1.0, set())
    assert moved.surprise == 6.0 and quiet.surprise == 1.0


def test_novelty_spreads_looks_and_open_anomalies_halve_it(graph: Graph) -> None:
    budget = AttentionBudget(graph)
    unit = Unit("cvr", ("country",))
    budget.mark(unit, HOUR, 1.2)
    assert budget.terms(unit, HOUR, {}, 1.0, set()).score == 0.0
    later = budget.terms(unit, HOUR + timedelta(hours=6), {}, 1.0, set())
    assert later.novelty == pytest.approx(0.632, abs=0.001)
    assert later.surprise == pytest.approx(2.2)
    handled = budget.terms(unit, HOUR + timedelta(hours=6), {}, 1.0, {"cvr"})
    assert handled.novelty == pytest.approx(later.novelty / 2)


def test_pending_data_gets_no_attention(graph: Graph) -> None:
    budget = AttentionBudget(graph)
    assert budget.terms(Unit("orders", ("country",)), HOUR, {"orders": 8.0}, 0.0, set()).score == 0.0


def test_payload_lists_every_candidate(graph: Graph) -> None:
    budget = AttentionBudget(graph)
    payload = AttentionBudget.payload(scores(budget, {}))
    assert set(payload.scores) == {u.key for u in budget.units}
    assert all(v >= 0 for v in payload.scores.values())


def test_a_broken_breakdown_leaves_the_candidates(graph: Graph) -> None:
    broken = graph.model_copy(
        update={
            "edges": [
                e.model_copy(update={"status": EdgeStatus.BROKEN}) if e.id == "b_orders_country" else e
                for e in graph.edges
            ]
        }
    )
    keys = {u.key for u in candidate_units(broken)}
    assert "orders[country]" not in keys and "orders[platform]" in keys
