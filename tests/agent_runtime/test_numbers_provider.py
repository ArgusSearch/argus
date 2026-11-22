"""Number check, tariff and cassette matching."""

from __future__ import annotations

import pytest

from argus.agent.examples import REQUEST, RESPONSE
from argus.agent.fake import FakeLlmClient
from argus.agent.numbers import FactBook, check
from argus.agent.provider import Cassette, CassetteMismatch, RecordingClient, ReplayClient, price, request_sha


def facts() -> FactBook:
    book = FactBook()
    book.add({"rel": -0.3641, "s": "0.607 vs 0.955, EUR -21,742/h"}, ["a3"])
    return book


def test_backed_and_tagged_report_passes() -> None:
    assert check("It fell -36.4% [a3]. It costs EUR 21,742 per hour. [a3]", facts()).ok


def test_unbacked_untagged_and_pseudo_citations_fail() -> None:
    result = check("It fell 99%. [a3] It costs EUR 21,742. Severity 21,742 [get_incident INC-0001].", facts())
    assert result.unbacked == ["99"]
    assert result.untagged == ["It costs EUR 21,742.", "Severity 21,742 [get_incident INC-0001]."]
    assert result.unknown_receipts and not result.ok


def test_receipts_without_results_back_nothing() -> None:
    book = FactBook()
    book.add({"x": 0.5}, [])  # a result with no receipt adds no facts
    assert not check("Half of it: 0.5 [a1].", book).ok


def test_price_is_never_guessed() -> None:
    assert price("claude-sonnet-5-5", {"input_tokens": 1_000_000}) == pytest.approx(2.0)
    assert price("claude-unknown", {"input_tokens": 1}) is None


def test_cassette_round_trip_and_strict_mismatch() -> None:
    recorder = RecordingClient(FakeLlmClient([RESPONSE]))
    recorder.create(REQUEST)
    replay = ReplayClient(recorder.cassette)
    replayed = replay.create(REQUEST)
    assert replayed.request_id is None  # recordings keep no provider request ids
    assert replayed.content[-1]["id"] == "toolu_investigate_an_0001_1_1"  # deterministic tool-use ids
    assert replayed.content[-1]["input"] == RESPONSE.content[-1]["input"] and replayed.usage == RESPONSE.usage
    changed = REQUEST.model_copy(update={"system": "different"})
    with pytest.raises(CassetteMismatch):
        ReplayClient(recorder.cassette).create(changed)
    lenient = ReplayClient(Cassette(list(recorder.cassette.lines)), strict=False)
    lenient.create(changed)
    assert lenient.drift == [REQUEST.key]
    assert request_sha(REQUEST).startswith("sha256:")


def test_scrub_keeps_backed_numbers_and_masks_the_rest() -> None:
    from argus.agent.numbers import UNVERIFIED, scrub

    text = scrub("It fell -36.4% at 2026-11-21 18:00, maybe 99.9% of revenue [a3].", facts())
    assert "-36.4%" in text and "2026-11-21 18:00" in text and "99.9" not in text and UNVERIFIED in text


def test_a_recurrence_vetoes_whatever_the_model_predicted() -> None:
    from argus.agent.investigate import canonical_placebo
    from argus.investigate.ledger import Hypothesis, LedgerEntry

    args = {"node": "x", "segment": {}, "window": {"start": "2026-11-21T18:00:00", "end": "2026-11-21T18:00:00"}}
    hyp = Hypothesis(statement="s", prediction="p", tool="placebo_test", input=args, expect="recurring", source="agent")
    entry = LedgerEntry(id="h1", hypothesis=hyp, status="validated", outcome="recurring", summary="3 of 5 weeks")
    canonical = canonical_placebo(entry)
    assert canonical.status == "refuted" and canonical.hypothesis.expect == "unusual"
    unusual = entry.model_copy(update={"outcome": "unusual", "status": "refuted"})
    assert canonical_placebo(unusual).status == "validated"


def test_ids_dates_and_versions_are_not_figures() -> None:
    from argus.agent.numbers import scrub

    text = (
        "INC-0001 waits on act_0001 (ad-pacer 1.7.0 back to pacer 1.6) since 2026-11-20 03:00 "
        "for three hours, until the 21st."
    )
    assert scrub(text, FactBook()) == text
    assert "[unverified]" in scrub("It cost 1,861 EUR.", FactBook())
