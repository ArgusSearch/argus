"""Background log traffic: innocent deploys and provider maintenance every day.

Without decoys the only deploy in the log would always be the cause, and the holdout check
would prove nothing. These entries change no data.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import numpy as np

from argus.contracts.world import CATEGORIES, COUNTRIES
from mockmart.sim import WorldParams

# service -> (major version, scope builder)
_SERVICES: tuple[tuple[str, str], ...] = (
    ("web-frontend", "web"),
    ("ios-app", "ios"),
    ("android-app", "android-staged"),
    ("search-service", "global"),
    ("recommendations", "global"),
    ("checkout-service", "global"),
    ("catalog-service", "category"),
)
_MAJOR = {"web-frontend": 3, "ios-app": 8, "android-app": 8, "search-service": 2}


def _scope(kind: str, rng: np.random.Generator) -> tuple[dict[str, list[str]], str]:
    if kind == "web":
        return {"platform": ["web"]}, "web"
    if kind == "ios":
        return {"platform": ["ios"]}, "iOS"
    if kind == "android-staged":
        country = str(rng.choice(COUNTRIES))
        return {"platform": ["android"], "country": [country]}, f"Android staged rollout in {country}"
    if kind == "category":
        category = str(rng.choice(CATEGORIES))
        return {"category": [category]}, f"{category} catalog"
    return {}, "all users"


def add_background_logs(params: WorldParams, rng: np.random.Generator) -> None:
    cfg = params.cfg
    minor: dict[str, int] = {}
    for day in range(cfg.days):
        day_start = cfg.start + timedelta(days=day)
        for _ in range(int(rng.poisson(3.0))):
            service, scope_kind = _SERVICES[int(rng.integers(len(_SERVICES)))]
            minor[service] = minor.get(service, 0) + 1
            if service == "android-app":
                version = f"8.2.{minor[service]}"
            else:
                version = f"{_MAJOR.get(service, 1)}.{minor[service] // 10}.{minor[service] % 10}"
            scope, where = _scope(scope_kind, rng)
            ts = day_start + timedelta(hours=int(rng.integers(8, 19)), minutes=int(rng.integers(60)))
            params.add_log(
                "log_deploys",
                _deploy(f"dep_{service}_{version}", ts, service, version, scope, f"{service} {version} ({where})"),
            )
        if day % 3 == 1:
            provider = str(rng.choice(["CardHub", "WalletGo"]))
            ts = day_start + timedelta(hours=2, minutes=int(rng.integers(0, 30)))
            params.add_log(
                "log_provider_status",
                {
                    "id": f"ps_{provider.lower()}_{day:02d}",
                    "ts": ts,
                    "kind": "maintenance",
                    "scope": {"provider": [provider]},
                    "description": f"{provider}: scheduled maintenance window, no customer impact expected",
                    "provider": provider,
                },
            )


def _deploy(
    dep_id: str, ts: Any, service: str, version: str, scope: dict[str, list[str]], description: str
) -> dict[str, Any]:
    return {
        "id": dep_id,
        "ts": ts,
        "kind": "release" if service.endswith("-app") else "deploy",
        "scope": scope,
        "description": description,
        "service": service,
        "version": version,
    }
