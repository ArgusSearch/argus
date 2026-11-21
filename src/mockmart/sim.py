"""MockMart core: a causal hourly marketplace with an ads business.

Generation runs in three steps so scenarios can intervene at the right level:

1. `base_params` builds the causal parameters (expected traffic, funnel rates, provider success
   probabilities, ad budgets, pacing) with daily and weekly shape and multi-level noise.
2. Scenarios mutate the parameters and append their logs and ground truth.
3. `sample` draws the counts bottom-up (Poisson traffic, binomial funnel steps), so the formula
   identities hold by construction: orders = payment_successes in every segment-hour.

Noise sits on several levels (global hour, country day, country hour) so a -3% total change is
not trivially visible, as in real data.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from argus.contracts.world import ADVERTISERS, CATEGORIES, CHANNELS, COUNTRIES, PLATFORMS, PROVIDERS

COUNTRY_WEIGHT = dict(zip(COUNTRIES, [0.30, 0.22, 0.22, 0.13, 0.13], strict=True))
PLATFORM_WEIGHT = dict(zip(PLATFORMS, [0.40, 0.35, 0.25], strict=True))
CHANNEL_WEIGHT = dict(zip(CHANNELS, [0.40, 0.30, 0.10, 0.20], strict=True))
CATEGORY_WEIGHT = dict(zip(CATEGORIES, [0.22, 0.24, 0.18, 0.12, 0.10, 0.14], strict=True))
# Conversion differs by country so that a traffic-mix shift moves the blended rate (Simpson's paradox, S5).
CART_RATE_COUNTRY = dict(zip(COUNTRIES, [1.10, 1.00, 1.05, 0.55, 1.00], strict=True))
AOV_CATEGORY = dict(zip(CATEGORIES, [140.0, 55.0, 80.0, 35.0, 40.0, 30.0], strict=True))

VIEW_RATE = 0.62
CART_RATE = 0.24
CHECKOUT_RATE = 0.52
ATTEMPT_RATE = 0.90
# PayCo takes half of the attempts, CardHub 60% of the rest, WalletGo the remainder.
PROVIDER_SPLIT = {"PayCo": 0.50, "CardHub": 0.60}
SUCCESS_P = {"PayCo": 0.95, "CardHub": 0.95, "WalletGo": 0.94}

ADS_PLATFORM_SHARE = dict(zip(PLATFORMS, [0.45, 0.35, 0.20], strict=True))
# advertiser -> (name, vertical, {country: daily budget EUR}, cpc EUR, ctr, conversion rate per click, aov EUR)
ADVERTISER_BOOK: dict[str, tuple[str, str, dict[str, float], float, float, float, float]] = {
    "adv_01": ("Nimbus Games", "mobile_games", {"DE": 3000, "FR": 2000, "UK": 2500}, 0.42, 0.021, 0.035, 18.0),
    "adv_02": ("Pixel Forge", "mobile_games", {"DE": 1800, "ES": 1200, "NL": 800}, 0.35, 0.025, 0.030, 15.0),
    "adv_03": ("Lumen Retail", "retail", {"DE": 2500, "FR": 1500}, 0.55, 0.015, 0.045, 64.0),
    "adv_04": ("Kite and Co", "retail", {"UK": 2000, "NL": 1000}, 0.48, 0.017, 0.040, 52.0),
    "adv_05": ("Orbit Play", "mobile_games", {"FR": 2200, "ES": 1500, "DE": 1200}, 0.38, 0.023, 0.032, 16.0),
    "adv_06": ("Harbor Home", "retail", {"DE": 1500, "UK": 1200, "FR": 900}, 0.60, 0.014, 0.050, 88.0),
}
assert tuple(ADVERTISER_BOOK) == ADVERTISERS


@dataclass(frozen=True)
class WorldConfig:
    seed: int = 7
    start: datetime = datetime(2026, 10, 12)  # a Monday
    days: int = 42
    live_days: int = 5
    base_sessions: float = 120_000.0

    @property
    def hours(self) -> int:
        return self.days * 24

    @property
    def end(self) -> datetime:
        return self.start + timedelta(days=self.days)

    @property
    def live_start(self) -> datetime:
        return self.end - timedelta(days=self.live_days)


@dataclass
class TruthEvent:
    """One injected change, as recorded in truth.duckdb. Only the bench reads it."""

    event_id: str
    scenario: str
    kind: str  # fault | red_herring | innocent | data
    start_ts: datetime
    end_ts: datetime | None
    root_node: str | None
    segment: dict[str, str]
    magnitude: dict[str, float]
    description: str
    expected: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorldParams:
    cfg: WorldConfig
    hours: pd.DatetimeIndex
    seg: pd.DataFrame  # one row per funnel segment: country, platform, channel, category
    mu_sessions: np.ndarray  # (H, S) expected sessions
    view_rate: np.ndarray  # (H, S)
    cart_rate: np.ndarray  # (H, S)
    checkout_rate: np.ndarray  # (H, S)
    attempt_rate: np.ndarray  # (H, S)
    success_p: dict[str, np.ndarray]  # provider -> (H, S)
    aov: np.ndarray  # (S,)
    ad_lines: pd.DataFrame  # one row per advertiser-country budget line
    ad_plan_share: np.ndarray  # (H,) share of the day's budget planned for the hour
    ad_budget: np.ndarray  # (H, L) daily budget in force per line
    ad_delivery: np.ndarray  # (H, L) delivered spend / planned spend (pacer behaviour + noise)
    logs: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    extra_delay_min: dict[str, np.ndarray] = field(default_factory=dict)  # table -> (H,) delay for late batches
    truth: list[TruthEvent] = field(default_factory=list)

    def seg_mask(self, **values: str) -> np.ndarray:
        mask = np.ones(len(self.seg), dtype=bool)
        for dim, value in values.items():
            mask &= self.seg[dim].to_numpy() == value
        return mask

    def hour_index(self, ts: datetime) -> int:
        return int((ts - self.cfg.start) / timedelta(hours=1))

    def add_log(self, table: str, row: dict[str, Any]) -> None:
        self.logs.setdefault(table, []).append(row)


def _lognormal(rng: np.random.Generator, sigma: float, size: Any) -> np.ndarray:
    return np.exp(rng.normal(-0.5 * sigma**2, sigma, size))


def base_params(cfg: WorldConfig, rng: np.random.Generator) -> WorldParams:
    hours = pd.date_range(cfg.start, periods=cfg.hours, freq="h")
    seg = pd.DataFrame(
        list(itertools.product(COUNTRIES, PLATFORMS, CHANNELS, CATEGORIES)),
        columns=["country", "platform", "channel", "category"],
    )
    weight = (
        seg.country.map(COUNTRY_WEIGHT)
        * seg.platform.map(PLATFORM_WEIGHT)
        * seg.channel.map(CHANNEL_WEIGHT)
        * seg.category.map(CATEGORY_WEIGHT)
    ).to_numpy()

    hod = hours.hour.to_numpy()
    weekend = hours.day_of_week.to_numpy() >= 5
    season = (1.0 + 0.5 * np.sin(2 * np.pi * (hod - 10) / 24)) * np.where(weekend, 1.12, 1.0)

    n_h, n_s = len(hours), len(seg)
    country_idx = seg.country.map({c: i for i, c in enumerate(COUNTRIES)}).to_numpy()
    day_idx = np.arange(n_h) // 24
    noise_global = _lognormal(rng, 0.02, n_h)
    noise_country_day = _lognormal(rng, 0.03, (cfg.days, len(COUNTRIES)))
    noise_country_hour = _lognormal(rng, 0.025, (n_h, len(COUNTRIES)))
    country_noise = noise_country_day[day_idx][:, country_idx] * noise_country_hour[:, country_idx]
    mu = cfg.base_sessions * season[:, None] * weight[None, :] * noise_global[:, None] * country_noise

    ones = np.ones((n_h, n_s))
    cart = CART_RATE * seg.country.map(CART_RATE_COUNTRY).to_numpy()
    success_p = {p: SUCCESS_P[p] * ones for p in PROVIDERS}

    lines = [
        {
            "advertiser_id": adv,
            "country": country,
            "base_budget": budget,
            "name": book[0],
            "vertical": book[1],
            "cpc": book[3],
            "ctr": book[4],
            "conv_rate": book[5],
            "aov": book[6],
        }
        for adv, book in ADVERTISER_BOOK.items()
        for country, budget in book[2].items()
    ]
    ad_lines = pd.DataFrame(lines)
    day_season = season.reshape(cfg.days, 24)
    ad_plan_share = (day_season / day_season.sum(axis=1, keepdims=True)).reshape(-1)
    ad_budget = np.tile(ad_lines.base_budget.to_numpy(dtype=float), (n_h, 1))
    ad_delivery = _lognormal(rng, 0.04, (n_h, len(ad_lines)))

    params = WorldParams(
        cfg=cfg,
        hours=hours,
        seg=seg,
        mu_sessions=mu,
        view_rate=VIEW_RATE * ones,
        cart_rate=cart[None, :] * ones,
        checkout_rate=CHECKOUT_RATE * ones,
        attempt_rate=ATTEMPT_RATE * ones,
        success_p=success_p,
        aov=seg.category.map(AOV_CATEGORY).to_numpy(dtype=float),
        ad_lines=ad_lines,
        ad_plan_share=ad_plan_share,
        ad_budget=ad_budget,
        ad_delivery=ad_delivery,
    )
    for _, line in ad_lines.iterrows():
        params.add_log(
            "log_ad_budgets",
            {
                "id": f"bud_{line.advertiser_id}_{line.country}",
                "ts": cfg.start - timedelta(days=1),
                "kind": "budget_set",
                "scope": {"advertiser_id": [line.advertiser_id], "country": [line.country]},
                "description": f"{line['name']} {line.country}: daily budget EUR {line.base_budget:.0f}, pacer 1.6",
                "advertiser_id": line.advertiser_id,
                "country": line.country,
                "daily_budget": float(line.base_budget),
                "pacer_version": "1.6",
            },
        )
    return params


def _frame(keys: pd.DataFrame, hours: pd.DatetimeIndex, values: dict[str, np.ndarray]) -> pd.DataFrame:
    """Long table: every (hour, key row) with the (H, K) value arrays flattened in the same order."""
    n_h, n_k = len(hours), len(keys)
    out = pd.DataFrame({"ts": np.repeat(hours.to_numpy(), n_k)})
    for col in keys.columns:
        out[col] = np.tile(keys[col].to_numpy(), n_h)
    for name, arr in values.items():
        out[name] = arr.reshape(n_h * n_k)
    return out


def sample(params: WorldParams, rng: np.random.Generator) -> dict[str, pd.DataFrame]:
    """Draw every fact table at full delivery (before micro-batching)."""
    sessions = rng.poisson(params.mu_sessions)
    views = rng.binomial(sessions, params.view_rate)
    carts = rng.binomial(views, params.cart_rate)
    checkouts = rng.binomial(carts, params.checkout_rate)
    attempts = rng.binomial(checkouts, params.attempt_rate)
    a_payco = rng.binomial(attempts, PROVIDER_SPLIT["PayCo"])
    a_card = rng.binomial(attempts - a_payco, PROVIDER_SPLIT["CardHub"])
    a_wallet = attempts - a_payco - a_card
    by_provider = {"PayCo": a_payco, "CardHub": a_card, "WalletGo": a_wallet}
    successes = {p: rng.binomial(a, params.success_p[p]) for p, a in by_provider.items()}
    orders = successes["PayCo"] + successes["CardHub"] + successes["WalletGo"]
    gmv = np.round(orders * params.aov[None, :] * _lognormal(rng, 0.03, orders.shape), 2)

    seg = params.seg
    funnel = _frame(
        seg,
        params.hours,
        {"sessions": sessions, "product_views": views, "carts": carts, "checkouts": checkouts},
    )
    orders_df = _frame(seg, params.hours, {"orders": orders, "gmv": gmv})

    pay_parts = []
    for provider in PROVIDERS:
        part = _frame(
            seg,
            params.hours,
            {"payment_attempts": by_provider[provider], "payment_successes": successes[provider]},
        )
        part["provider"] = provider
        pay_parts.append(part)
    payments = (
        pd.concat(pay_parts, ignore_index=True)
        .groupby(["ts", "country", "platform", "provider"], as_index=False)[["payment_attempts", "payment_successes"]]
        .sum()
    )

    ads, plan = _sample_ads(params, rng)
    return {
        "fact_funnel_hourly": funnel,
        "fact_payments_hourly": payments,
        "fact_orders_hourly": orders_df,
        "fact_ads_hourly": ads,
        "fact_ad_plan_hourly": plan,
    }


def _sample_ads(params: WorldParams, rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    lines = params.ad_lines
    planned = params.ad_budget * params.ad_plan_share[:, None]  # (H, L)
    delivered = planned * params.ad_delivery
    plan = _frame(lines[["advertiser_id", "country"]], params.hours, {"planned_spend": np.round(planned, 2)})

    cpc = lines.cpc.to_numpy()[None, :]
    ctr = lines.ctr.to_numpy()[None, :]
    conv = lines.conv_rate.to_numpy()[None, :]
    aov = lines.aov.to_numpy()[None, :]
    parts = []
    for platform in PLATFORMS:
        target = delivered * ADS_PLATFORM_SHARE[platform]
        impressions = rng.poisson(target / (cpc * ctr))
        clicks = rng.binomial(impressions, np.broadcast_to(ctr, impressions.shape))
        spend = np.round(clicks * cpc * _lognormal(rng, 0.02, clicks.shape), 2)
        conversions = rng.binomial(clicks, np.broadcast_to(conv, clicks.shape))
        attributed = np.round(conversions * aov * _lognormal(rng, 0.05, clicks.shape), 2)
        part = _frame(
            lines[["advertiser_id", "country"]],
            params.hours,
            {
                "ad_impressions": impressions,
                "ad_clicks": clicks,
                "ad_spend": spend,
                "ad_conversions": conversions,
                "attributed_gmv": attributed,
            },
        )
        part["platform"] = platform
        parts.append(part)
    ads = pd.concat(parts, ignore_index=True)
    return ads, plan
