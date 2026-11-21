"""Package #4: named playbooks on the investigation path."""

from __future__ import annotations

from argus.graph.store import load_seed_graph
from argus.investigate.playbook import STEPS, choose_playbook

GRAPH = load_seed_graph()


def test_playbook_is_named_after_the_node_family_and_direction() -> None:
    assert choose_playbook(GRAPH, "payment_success_rate", "down").name == "Revenue drop playbook"
    assert choose_playbook(GRAPH, "ad_spend", "up").name == "Ad spend spike playbook"
    assert choose_playbook(GRAPH, "cpa", "up").id == "ads_spike"
    assert choose_playbook(GRAPH, "sessions", "down").name == "Traffic drop playbook"


def test_every_trail_step_maps_to_a_named_playbook_step() -> None:
    pb = choose_playbook(GRAPH, "orders", "down")
    assert pb.tag("holdout", "placebo_test", {})["label"] == "Placebo"
    assert pb.tag("holdout", "holdout_check", {})["label"] == "Hypothesis tests"
    planned = {"ledger": {"hypothesis": {"source": "planner:llm"}}}
    assert pb.tag("holdout", "holdout_check", planned)["step"] == "planner"
    tag = pb.tag("decompose", "mix_rate_split", {})
    assert (tag["label"], tag["of"]) == ("Mix vs rate", len(STEPS))
    run = pb.run_status({"data_freshness", "verdict"})
    assert [r["status"] for r in run].count("done") == 2 and run[-1] == {
        "step": "verdict",
        "label": "Verdict",
        "status": "done",
    }
