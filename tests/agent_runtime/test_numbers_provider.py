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
