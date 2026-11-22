"""Provider response validation and an HTTPS transport with a fixed set of endpoints."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time
from http.client import HTTPException
from typing import Any, Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from argus.contracts.graph import Unit

ProviderId = Literal["plausible", "stripe"]
PROVIDERS: tuple[ProviderId, ...] = ("plausible", "stripe")
ENDPOINTS = {
    "plausible": "https://plausible.io/api/v2/query",
    "payment_intents": "https://api.stripe.com/v1/payment_intents",
    "subscriptions": "https://api.stripe.com/v1/subscriptions",
}
MAX_RESPONSE = 4 * 1024 * 1024
DAYS = 35


class ProviderError(ValueError):
    """A safe error that can be reported to the operator."""


class RefuseRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Fetch(Protocol):
    def __call__(
        self, endpoint: str, key: str, *, params: dict[str, str | int] | None = None, body: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...


def request(
    endpoint: str, key: str, *, params: dict[str, str | int] | None = None, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    url = ENDPOINTS[endpoint]
    if params:
        url += "?" + urlencode(params)
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = Request(url, headers=headers, data=json.dumps(body).encode() if body is not None else None)
    try:
        with build_opener(ProxyHandler({}), RefuseRedirects()).open(req, timeout=5) as response:
            content = response.read(MAX_RESPONSE + 1)
        if len(content) > MAX_RESPONSE:
            raise ProviderError("The provider response exceeded the sync limit.")
        return obj(json.loads(content))
    except HTTPError as err:
        err.close()
        if err.code in (401, 403, 404):
            raise ProviderError("Check the API key, its permissions, and the selected site or account.") from None
        if err.code == 429:
            raise ProviderError("The provider is rate limiting requests. Try again shortly.") from None
        raise ProviderError("The provider refused the request. Check the connection settings and try again.") from None
    except (URLError, OSError, HTTPException, json.JSONDecodeError, UnicodeError):
        raise ProviderError("The provider could not be reached or returned an unreadable response.") from None


def obj(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProviderError("The provider returned an unexpected response.")
    return value


def items(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise ProviderError("The provider returned an unexpected response.")
    return value


def count(value: object) -> int:
    if type(value) is not int or not 0 <= value < 2**53:
        raise ProviderError("The provider returned an invalid count or amount.")
    return value


def label(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048 or not value.isprintable():
        raise ProviderError("The provider returned an invalid dimension.")
    return value


@dataclass(frozen=True)
class Metric:
    id: str
    description: str
    dimension: str | None = None
    unit: Unit = "count"
    numerator: str | None = None
    denominator: str | None = None

    @property
    def table(self) -> str:
        return f"fact_{self.id}"


@dataclass(frozen=True)
class Row:
    metric: str
    day: date
    value: int
    dimension: str = ""

    def values(self) -> tuple[str, datetime, str, int]:
        return self.metric, datetime.combine(self.day, time()), self.dimension, self.value


@dataclass(frozen=True)
class Report:
    latest_day: date
    rows: list[Row]
