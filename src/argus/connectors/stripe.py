"""Read-only Stripe test payments and subscriptions."""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from argus.connectors.provider import DAYS, Fetch, Metric, ProviderError, Report, Row, count, items, label, obj

METRICS = (
    Metric(
        "stripe_gross_payments",
        "Stripe test gross payment receipts in minor currency units, by intent creation day",
    ),
    Metric("stripe_successful_payments", "Stripe test payment intents that succeeded, by creation day"),
    Metric("stripe_resolved_payments", "Stripe test intents with a successful, failed or canceled outcome"),
    Metric("stripe_new_subscriptions", "Stripe test subscriptions created, including those later canceled"),
    Metric(
        "stripe_payment_success_rate",
        "Successful Stripe test payment intents divided by resolved test intents",
        unit="share",
        numerator="stripe_successful_payments",
        denominator="stripe_resolved_payments",
    ),
)
PAGE = 100
MAX_PAGES = 10
TEST_KEY = re.compile(r"[sr]k_test_[a-zA-Z0-9_]+")


def currency_code(value: str) -> str:
    if not re.fullmatch(r"[a-zA-Z]{3}", value):
        raise ProviderError("Enter a three-letter Stripe currency code, such as EUR.")
    return value.lower()


def validate_key(value: str) -> None:
    if not TEST_KEY.fullmatch(value):
        raise ProviderError("Use a Stripe test secret key or a restricted test key.")


def _list(fetch: Fetch, endpoint: str, key: str, start: date, end: date) -> list[dict[str, Any]]:
    params: dict[str, int | str] = {
        "limit": PAGE,
        "created[gte]": int(datetime.combine(start, time(), UTC).timestamp()),
        "created[lt]": int(datetime.combine(end, time(), UTC).timestamp()),
    }
    if endpoint == "subscriptions":
        params["status"] = "all"
    seen: set[str] = set()
    records: list[dict[str, Any]] = []
    for _ in range(MAX_PAGES):
        response = fetch(endpoint, key, params=params.copy())
        page = [obj(row) for row in items(response.get("data"))]
        for row in page:
            row_id = label(row.get("id"))
            if row.get("livemode") is not False or row_id in seen:
                raise ProviderError("Stripe returned live-mode or duplicate records. No data was imported.")
            seen.add(row_id)
        records.extend(page)
        if response.get("has_more") is False:
            return records
        if not page or response.get("has_more") is not True:
            raise ProviderError("Stripe returned an invalid page.")
        params["starting_after"] = page[-1]["id"]
    raise ProviderError("This test account exceeds the current sync limit.")


def _day(row: dict[str, Any], start: date, end: date) -> date:
    try:
        day = datetime.fromtimestamp(count(row.get("created")), UTC).date()
    except (ValueError, OverflowError, OSError):
        raise ProviderError("Stripe returned an invalid creation date.") from None
    if not start <= day < end:
        raise ProviderError("Stripe returned records outside the requested period.")
    return day


def sync(fetch: Fetch, key: str, currency: str, today: date) -> Report:
    validate_key(key)
    start = today - timedelta(days=DAYS)
    totals: dict[date, Counter[str]] = {start + timedelta(days=i): Counter() for i in range(DAYS)}
    for row in _list(fetch, "payment_intents", key, start, today):
        day = _day(row, start, today)
        status = label(row.get("status"))
        if status == "succeeded":
            totals[day]["stripe_successful_payments"] += 1
            if label(row.get("currency")) == currency:
                totals[day]["stripe_gross_payments"] += count(row.get("amount_received"))
        if status in {"succeeded", "canceled"} or (
            status == "requires_payment_method" and row.get("last_payment_error") is not None
        ):
            totals[day]["stripe_resolved_payments"] += 1
    for row in _list(fetch, "subscriptions", key, start, today):
        day = _day(row, start, today)
        totals[day]["stripe_new_subscriptions"] += 1
    return Report(
        today - timedelta(days=1),
        [
            Row(metric.id, day, total[metric.id])
            for day, total in totals.items()
            for metric in METRICS
            if not metric.numerator
        ],
    )
