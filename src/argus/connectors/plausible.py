"""Plausible Stats API v2. Daily dates follow the site's reporting timezone."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from argus.connectors.provider import DAYS, Fetch, Metric, ProviderError, Report, Row, count, items, label, obj

METRICS = (
    Metric("plausible_visitors", "Plausible daily unique visitors in the site's reporting timezone"),
    Metric("plausible_visits_by_source", "Plausible daily visits by acquisition source", "traffic_source"),
    Metric("plausible_pageviews", "Plausible daily pageviews by page path", "page_path"),
    Metric("plausible_conversions", "Plausible daily goal completions by goal", "goal"),
)
PAGE = 500
MAX_ROWS = 2000
SITE = re.compile(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]{0,251}[a-zA-Z0-9])?")


def site_id(value: str) -> str:
    if not SITE.fullmatch(value) or "." not in value or ".." in value:
        raise ProviderError("Enter the Plausible site domain, such as example.com.")
    return value


def _day(value: object) -> date:
    try:
        day = label(value)
        parsed = date.fromisoformat(day)
        if parsed.isoformat() == day:
            return parsed
    except ValueError:
        pass
    raise ProviderError("Plausible returned an invalid reporting date.")


def _query(
    fetch: Fetch, key: str, site: str, measure: str, period: str | list[str], dimension: str | None = None
) -> tuple[list[dict[str, Any]], list[date]]:
    results: list[dict[str, Any]] = []
    days: list[date] = []
    for offset in range(0, MAX_ROWS, PAGE):
        response = fetch(
            "plausible",
            key,
            body={
                "site_id": site,
                "metrics": [measure],
                "date_range": period,
                "dimensions": ["time:day", *([dimension] if dimension else [])],
                "include": {"time_labels": dimension is None, "total_rows": True},
                "pagination": {"limit": PAGE, "offset": offset},
            },
        )
        meta = obj(response.get("meta"))
        total = count(meta.get("total_rows"))
        if total > MAX_ROWS:
            raise ProviderError("This site exceeds the current breakdown limit for a sync.")
        page = [obj(row) for row in items(response.get("results"))]
        if len(page) != min(PAGE, max(0, total - offset)):
            raise ProviderError("Plausible returned an incomplete set of rows. Try again.")
        if dimension is None:
            days = [_day(value) for value in items(meta.get("time_labels"))]
        results.extend(page)
        if len(results) >= total:
            return results, days
    raise ProviderError("Plausible did not finish paging. Try again.")


def _normalize(metric: Metric, records: list[dict[str, Any]], days: set[date]) -> list[Row]:
    values: dict[tuple[date, str], int] = {}
    for record in records:
        dims = items(record.get("dimensions"))
        nums = items(record.get("metrics"))
        if len(dims) != (2 if metric.dimension else 1) or len(nums) != 1:
            raise ProviderError("Plausible returned an unexpected breakdown.")
        day = _day(dims[0])
        if day not in days:
            raise ProviderError("Plausible returned records outside the requested period.")
        name = label(dims[1]) if metric.dimension else ""
        if (day, name) in values:
            raise ProviderError("Plausible returned duplicate rows. Try again.")
        values[day, name] = count(nums[0])
    if metric.dimension is None:
        for day in days:
            values.setdefault((day, ""), 0)
    return [Row(metric.id, day, value, name) for (day, name), value in sorted(values.items())]


def sync(fetch: Fetch, key: str, site: str) -> Report:
    _, today = _query(fetch, key, site, "visitors", "day")
    if len(today) != 1:
        raise ProviderError("Plausible did not return the current reporting date.")
    last = today[0] - timedelta(days=1)
    first = today[0] - timedelta(days=DAYS)
    period = [first.isoformat(), last.isoformat()]
    visitors, dates = _query(fetch, key, site, "visitors", period)
    days = {first + timedelta(days=i) for i in range(DAYS)}
    if dates != sorted(days):
        raise ProviderError("Plausible did not return a complete date range.")
    rows = _normalize(METRICS[0], visitors, days)
    for metric, measure, dimension in zip(
        METRICS[1:], ("visits", "pageviews", "events"), ("visit:source", "event:page", "event:goal"), strict=True
    ):
        records, _ = _query(fetch, key, site, measure, period, dimension)
        rows.extend(_normalize(metric, records, days))
    return Report(max(days), rows)
