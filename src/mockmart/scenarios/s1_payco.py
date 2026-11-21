"""S1: PayCo fails for Android users in Germany, and an Android release ships everywhere in the same hour.

This is the track brief's own example. The trap: an obvious suspect (the release) that is wrong, and a
total that barely moves. Argus must conclude SUPPORTED_CAUSE "PayCo, DE-android" and list the release
under "ruled out", because Android in the other countries is normal (holdout check).

Randomised per seed: onset hour (at least 48 quiet live hours before it), duration 6..12 h, and the
PayCo success rate during the fault (0.60..0.72, normal is 0.95).
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np

from mockmart.sim import SUCCESS_P, TruthEvent, WorldParams

ROOT_NODE = "payment_success_rate"
SEGMENT = {"country": "DE", "platform": "android", "provider": "PayCo"}
RELEASE_ID = "dep_android-app_8.3.0"
QUIET_LIVE_HOURS = 48


def apply_s1(params: WorldParams, rng: np.random.Generator) -> None:
    cfg = params.cfg
    live_h = params.hour_index(cfg.live_start)
    if cfg.live_days * 24 < QUIET_LIVE_HOURS + 12 + 24:
        raise ValueError(f"S1 needs at least {QUIET_LIVE_HOURS + 36} live hours (live_days >= 4)")
    duration = int(rng.integers(6, 13))
    onset_h = int(rng.integers(live_h + QUIET_LIVE_HOURS, cfg.hours - 24 - duration + 1))
    p_fault = float(rng.uniform(0.60, 0.72))

    mask = params.seg_mask(country="DE", platform="android")
    params.success_p["PayCo"][onset_h : onset_h + duration, mask] = p_fault
    t0 = params.hours[onset_h].to_pydatetime()
    t1 = t0 + timedelta(hours=duration)

    release_ts = t0 - timedelta(minutes=int(rng.integers(2, 10)))
    params.add_log(
        "log_deploys",
        {
            "id": RELEASE_ID,
            "ts": release_ts,
            "kind": "release",
            "scope": {"platform": ["android"]},
            "description": "android-app 8.3.0 rolled out to 100% of Android users in all countries",
            "service": "android-app",
            "version": "8.3.0",
        },
    )
    status_ts = t0 - timedelta(minutes=int(rng.integers(1, 8)))
    status_scope = {"provider": ["PayCo"], "country": ["DE"], "platform": ["android"]}
    params.add_log(
        "log_provider_status",
        {
            "id": "ps_payco_degraded",
            "ts": status_ts,
            "kind": "degraded",
            "scope": status_scope,
            "description": "PayCo: elevated decline rates for Android SDK payments in Germany",
            "provider": "PayCo",
        },
    )
    params.add_log(
        "log_provider_status",
        {
            "id": "ps_payco_resolved",
            "ts": t1 + timedelta(minutes=int(rng.integers(5, 40))),
            "kind": "resolved",
            "scope": status_scope,
            "description": "PayCo: Android SDK payments in Germany recovered",
            "provider": "PayCo",
        },
    )
    params.truth.append(
        TruthEvent(
            event_id="s1_payco_outage",
            scenario="s1",
            kind="fault",
            start_ts=t0,
            end_ts=t1,
            root_node=ROOT_NODE,
            segment=dict(SEGMENT),
            magnitude={"success_rate_normal": SUCCESS_P["PayCo"], "success_rate_fault": round(p_fault, 4)},
            description="PayCo payment success for Android in DE drops; release 8.3.0 ships everywhere",
            expected={
                "verdict": "SUPPORTED_CAUSE",
                "root_node": ROOT_NODE,
                "segment": dict(SEGMENT),
                "evidence": "ps_payco_degraded",
                "ruled_out": [RELEASE_ID],
                "max_detection_delay_hours": 3,
            },
        )
    )
    params.truth.append(
        TruthEvent(
            event_id="s1_release_red_herring",
            scenario="s1",
            kind="red_herring",
            start_ts=release_ts,
            end_ts=None,
            root_node=None,
            segment={"platform": "android"},
            magnitude={},
            description="android-app 8.3.0 release in all countries; it does not affect any metric",
        )
    )
