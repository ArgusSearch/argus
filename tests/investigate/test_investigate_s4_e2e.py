"""S4 (the Almedia case) end to end: pacer 1.7 overburns the DE and FR budget lines.

The formula walk alone ends on impressions_per_session ("the ad system served more"), where no logged
cause can attach. The ratio identity ad_spend = planned_spend x pacing_ratio is also exact, ends on the
pacing ratio the budget logs attach to, and shows the plan did not move. The investigator must follow it,
rule out a traffic change, and confirm the pacer rollout with the untouched UK/ES/NL lines as control.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from argus.contracts.findings import EvidenceRef, Verdict
from argus.investigate.__main__ import run_world
from argus.investigate.procedure import group_batches, is_batch
from mockmart.sim import WorldConfig
from mockmart.truth import read_truth
from mockmart.world import generate


@pytest.mark.e2e
@pytest.mark.parametrize("seed", [1, 2])
def test_s4_follows_the_pacing_ratio_to_the_pacer_rollout(tmp_path, seed: int) -> None:  # type: ignore[no-untyped-def]
    paths = generate("s4", WorldConfig(seed=seed), tmp_path)
    runtime = run_world(paths.world)
    truth = next(e for e in read_truth(paths.truth) if e["kind"] == "fault")["expected"]
    supported = [i for i in runtime.book.incidents.values() if i.verdict is Verdict.SUPPORTED_CAUSE]
    assert len(supported) == 1
    f = supported[0].findings
    assert f.root is not None and f.root.evidence is not None
    assert f.root.node in truth["root_nodes_any"]
    assert f.root.evidence.ref in truth["evidence_any"]
    walked = [s for s in f.trail if s.kind == "decompose" and s.data.get("decomposition")]
    assert walked and walked[0].data["decomposition"] == "identity via pacing_ratio"
    refuted = {r.hypothesis for r in f.ruled_out}
    assert "a change in sessions drove ad_spend" in refuted
    assert "a change in planned spend drove ad_spend" in refuted
    assert f.explained_share >= 0.8
    others = [i for i in runtime.book.incidents.values() if i is not supported[0]]
    assert all(i.verdict is Verdict.UNEXPLAINED for i in others)


def test_batch_rollouts_become_one_candidate_with_the_union_scope() -> None:
    ts = datetime(2026, 11, 19, 23, 11)

    def change(adv: str, country: str) -> EvidenceRef:
        return EvidenceRef(
            log="log_ad_budgets",
            ref=f"pacer_{adv}_{country}",
            ts=ts,
            kind="pacer_change",
            description=f"{adv} {country}: pacer 1.6 -> 1.7",
            scope={"advertiser_id": [adv], "country": [country]},
        )

    deploy = EvidenceRef(
        log="log_deploys",
        ref="dep_ad-pacer_1.7.0",
        ts=ts,
        kind="deploy",
        description="pacer",
        scope={"country": ["DE", "FR"]},
    )
    grouped = group_batches([change("adv_01", "DE"), change("adv_01", "FR"), change("adv_03", "DE"), deploy])
    assert len(grouped) == 2
    batch = next(e for e in grouped if is_batch(e))
    assert batch.ref == "pacer_adv_01_DE"
    assert batch.scope == {"advertiser_id": ["adv_01", "adv_03"], "country": ["DE", "FR"]}
    assert "pacer_adv_03_DE" in batch.description
    assert not is_batch(deploy)
