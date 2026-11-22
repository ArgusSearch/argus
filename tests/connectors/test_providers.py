from __future__ import annotations

import json
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

import pytest

from argus.connectors import plausible, provider, stripe
from argus.connectors.provider import DAYS, ProviderError, Row

FIXTURES = Path(__file__).parent / "fixtures"


def plausible_response(endpoint, _key, *, body, increase=0):
    assert endpoint == "plausible"
    assert body["site_id"] == "example.com"
    fixture = json.loads((FIXTURES / "plausible.json").read_text())
    metric = body["metrics"][0]
    day = date.fromisoformat(fixture["report_day"])
    if body["date_range"] == "day":
        rows, dates = [], [day.isoformat()]
    else:
        dates = [(day - timedelta(days=n)).isoformat() for n in range(DAYS, 0, -1)]
        assert body["date_range"] == [dates[0], dates[-1]]
        rows = fixture[metric]
        if metric == "visitors":
            rows[-1]["metrics"][0] += increase
    limit, offset = body["pagination"]["limit"], body["pagination"]["offset"]
    return {"results": rows[offset : offset + limit], "meta": {"time_labels": dates, "total_rows": len(rows)}}


def stripe_response(endpoint, _key, *, params):
    fixture = json.loads((FIXTURES / "stripe.json").read_text())
    pages = fixture[endpoint]
    offset = 1 if "starting_after" in params else 0
    if endpoint == "subscriptions":
        assert params["status"] == "all"
    if offset:
        assert params["starting_after"] == "pi_example_eur"
    return pages[offset]


def test_plausible_normalizes_totals_and_breakdowns(monkeypatch):
    monkeypatch.setattr(plausible, "PAGE", 1)
    report = plausible.sync(plausible_response, "fixture", "example.com")
    day = date(2026, 11, 21)
    assert report.latest_day == day
    assert Row("plausible_visitors", day, 93) in report.rows
    assert Row("plausible_visitors", day - timedelta(days=2), 0) in report.rows
    assert Row("plausible_visits_by_source", day, 48, "Search") in report.rows
    assert Row("plausible_pageviews", day, 17, "/pricing") in report.rows
    assert Row("plausible_conversions", day, 7, "Sign up") in report.rows


def test_stripe_uses_test_records_and_never_sums_currencies():
    report = stripe.sync(stripe_response, "rk_test_fixture", "eur", date(2026, 11, 22))
    day = date(2026, 11, 21)
    assert report.latest_day == day
    assert Row("stripe_gross_payments", day, 2345) in report.rows
    assert Row("stripe_successful_payments", day, 2) in report.rows
    assert Row("stripe_resolved_payments", day, 3) in report.rows
    assert Row("stripe_new_subscriptions", day, 1) in report.rows


def test_stripe_refuses_live_keys_and_live_responses():
    with pytest.raises(ProviderError, match="test secret key"):
        stripe.sync(stripe_response, "sk_live_fixture", "eur", date(2026, 11, 22))

    def live_mode(endpoint, key, *, params):
        response = stripe_response(endpoint, key, params=params)
        response["data"][0]["livemode"] = True
        return response

    with pytest.raises(ProviderError, match="live-mode"):
        stripe.sync(live_mode, "rk_test_fixture", "eur", date(2026, 11, 22))


def test_transport_uses_fixed_https_endpoints_without_proxies_or_redirects(monkeypatch):
    requests = []

    class Opener:
        def open(self, req, timeout):
            requests.append(req)
            assert timeout == 5
            return BytesIO(b'{"results": []}')

    def opener(proxies, redirects):
        assert proxies.proxies == {}
        assert redirects.redirect_request(None, None, 302, "", {}, "https://untrusted.example") is None
        return Opener()

    monkeypatch.setattr(provider, "build_opener", opener)
    reply = provider.request("plausible", "fixture-key", body={"site_id": "example.com"})
    assert reply == {"results": []}
    assert requests[0].full_url == "https://plausible.io/api/v2/query"
    assert requests[0].get_header("Authorization") == "Bearer fixture-key"
