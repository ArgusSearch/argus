import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from argus.agent.actions import Proposer
from argus.agent.journal import Journal
from argus.agent.memory import JsonlCaseMemory, proposal_policy
from argus.agent.types import CaseNote, Decision, RunSummary
from argus.contracts.findings import Incident
from argus.remediation import RemediationService
from mockmart.sim import WorldConfig
from mockmart.world import generate

DEPLOY = "dep_ad-pacer_1.7.0"
PLAYBOOK = "rollback_pacer"
PAST = datetime(2026, 11, 19)


def note(**kwargs: object) -> CaseNote:
    return CaseNote.model_validate(
        {
            "case_id": "INC-0001",
            "sim_ts": PAST,
            "fingerprint": "5e4bb2",
            "root_node": "pacing_ratio",
            "segment_dims": ["country"],
            "verdict": "SUPPORTED_CAUSE",
            "cause_kind": "deploy:ad-pacer",
            "cause_ref": DEPLOY,
            "deciding_checks": ["holdout_check"],
            "playbook_id": PLAYBOOK,
            "decision": "deny",
        }
        | kwargs
    )


def test_case_memory_is_past_only_and_ranks_deterministically(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    memory = JsonlCaseMemory(path)
    high = note(case_id="INC-0002")
    path.write_text(high.model_dump_json())  # no terminal newline in the seed file
    memory.remember(note(case_id="INC-0003", sim_ts=PAST + timedelta(hours=1)))
    memory.remember(note(case_id="INC-0004", cause_kind="deploy:other"))
    memory.remember(note(case_id="INC-0005", root_node="orders"))
    memory.remember(note(case_id="INC-0006", root_node="orders", cause_kind="deploy:other"))
    notes = memory.recall(
        root_node="pacing_ratio",
        segment={"country": "DE"},
        cause_kind="deploy:ad-pacer",
        as_of=PAST + timedelta(hours=1),
    )
    assert [result.case_id for result in notes] == ["INC-0002", "INC-0004", "INC-0005"]
    with pytest.raises(ValueError, match="numbers-free"):
        memory.remember(note(deciding_checks=["orders fell by 90 percent"]))
    assert len(path.read_text().splitlines()) == 5


def test_exact_denial_and_family_effect_policy() -> None:
    assert proposal_policy([note()], PLAYBOOK, DEPLOY) == "suppress_denied"
    assert proposal_policy([note()], PLAYBOOK, "dep_ad-pacer_1.8.0") == "propose"
    no_effect = note(decision="approve", effect="NO_EFFECT")
    assert proposal_policy([no_effect], PLAYBOOK, "dep_ad-pacer_1.8.0") == "suppress_no_effect"
    assert proposal_policy([no_effect], PLAYBOOK, "dep_other_1.7.0") == "propose"
    assert proposal_policy([note(decision="approve", effect="VERIFIED")], PLAYBOOK, DEPLOY) == "propose_with_precedent"


@pytest.mark.e2e
def test_remediation_denial_is_stored_and_prevents_a_second_proposal(tmp_path: Path) -> None:
    world = generate("s4", WorldConfig(seed=1), tmp_path / "world").world
    fixture = Path(__file__).resolve().parents[2] / "fixtures/s4/incidents.json"
    incident = Incident.model_validate(json.loads(fixture.read_bytes())[0])
    clock = incident.findings.as_of
    memory = JsonlCaseMemory(tmp_path / "cases.jsonl")

    def for_case(path: Path, *, persistent: bool = True) -> tuple[Proposer, RemediationService, Journal]:
        journal = Journal()
        journal.start_run(
            RunSummary(
                run_id="run_0001",
                kind="investigate",
                mode="live",
                sim_ts=clock,
                anomaly_id=incident.findings.anomaly_id,
                status="done",
            )
        )
        proposer: list[Proposer] = []
        engine = RemediationService(
            world,
            incidents=lambda _: incident,
            clock=lambda: clock,
            publish=lambda e: proposer[0].publish(e),
            state_dir=path,
            background=False,
        )
        proposer.append(Proposer(journal, engine, memory if persistent else None))
        return proposer[0], engine, journal

    first, service, _ = for_case(tmp_path / "first")
    first.on_incident(incident, "opened")
    (proposed,) = service.proposals()
    service.decide(proposed.id, proposed.digest, Decision(decision="deny", principal="operator", at=clock), "deny")
    clock += timedelta(hours=1)
    incident.findings.as_of = clock
    recalled = memory.recall(
        root_node=incident.root_node, segment=incident.segment, cause_kind="deploy:ad-pacer", as_of=clock
    )
    assert len(recalled) == 1 and recalled[0].decision == "deny"
    second, service, journal = for_case(tmp_path / "second")
    second.on_incident(incident, "opened")
    assert service.proposals() == []
    (record,) = journal.records
    assert record.kind == "memory" and "denied" in record.text
    assert record.args and record.args["policy"] == "suppress_denied"
    clean, service, _ = for_case(tmp_path / "clean", persistent=False)
    clean.on_incident(incident, "opened")
    assert len(service.proposals()) == 1

    memory = JsonlCaseMemory(tmp_path / "approved.jsonl")
    memory.remember(note(decision="approve", effect="VERIFIED"))
    approved, service, journal = for_case(tmp_path / "approved")
    approved.on_incident(incident, "opened")
    assert len(service.proposals()) == 1
    assert journal.records[0].args and journal.records[0].args["policy"] == "propose_with_precedent"

    memory.path.write_text('{"untrusted":"orders fell by 90 percent"}\n')
    fallback, service, journal = for_case(tmp_path / "fallback")
    fallback.on_incident(incident, "opened")
    assert len(service.proposals()) == 1
    assert journal.records[0].kind == "memory" and "unavailable" in journal.records[0].text
