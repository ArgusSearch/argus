# SUPPORTED CAUSE · Payment success rate -36.4% in DE / android / PayCo: PayCo: elevated decline rates for Android SDK payments in Germany

INC-0001 · state resolved · opened 2026-11-21 18:00 UTC · as_of 2026-11-21 20:00

## What happened

Payment success rate moved -2.40% [r225] against its expectation (observed 0.9249 [r225], expected 0.9477 [r225]).
Inside DE / android / PayCo, payment success rate moved -36.4% [r236]; this segment explains 100% of the deviation.
Evidence: PayCo: elevated decline rates for Android SDK payments in Germany (log_provider_status `ps_payco_degraded`, 2026-11-21 17:53) [r238].

## Impact

-310.7 orders per hour [r236], EUR -21,742 GMV per hour [r246], EUR -21,742 so far over 1 h [r246].

## Where the change came from (LMDI on orders, exact)

| factor | share of the change |
| --- | --- |
| payment_success_rate | +103% [r245] |
| sessions | +17% [r244] |
| checkout_rate | -10% [r244] |
| attempt_rate | -5% [r245] |
| cart_rate | -4% [r244] |
| view_rate | -2% [r244] |

## Ruled out

- android-app 8.3.0 rolled out to 100% of Android users in all countries: predicted "everything in the event's scope moves, not only DE / android / PayCo"; refuted (holdout normal: +0.0% (z +0.0) outside the segment vs -36.4% inside) [r240]
- checkout-service 1.2.6 (all users): predicted "everything in the event's scope moves, not only DE / android / PayCo"; refuted (holdout normal: +0.1% (z +0.5) outside the segment vs -36.4% inside) [r241]

## Still uncertain

- Whether the fault is inside PayCo or in our PayCo integration.

## Suggested action (needs human approval)

Route DE-android payments from PayCo to WalletGo until PayCo recovers.

## Lifecycle

- 2026-11-21 18:00 open: an_0001
- 2026-11-21 18:00 investigating: fixed opening started
- 2026-11-21 18:00 explained: SUPPORTED_CAUSE
- 2026-11-22 00:00 monitoring: root segment z +0.4 at 2026-11-22 00:00
- 2026-11-22 02:00 resolved: 3 consecutive normal hours
- severity (cumulative EUR impact while open): EUR 102,376

## Investigation trail

1. freshness: all source tables complete -> continue [r226]
2. identities: identities hold -> continue [r227] [r228]
3. calendar: 0 planned event(s) in force, none plans payment_success_rate in all segments -> continue: not an expected change [r229]
4. decompose: payment_success_rate has no formula children -> localise payment_success_rate directly
5. decompose: country: mix +0.00001, rate -0.02280; platform: mix -0.00024, rate -0.02255; provider: mix +0.00015, rate -0.02294 -> rate effect: localise the rate [r230] [r231] [r232]
6. segment: country=DE AND platform=android AND provider=PayCo explains 100% of the deviation (-36.4%) -> root segment DE / android / PayCo [r233] [r230] [r231] [r232] [r234] [r235] [r236]
7. segment: root segment deviates since 2026-11-21 18:00 -> align evidence with the root onset [r237]
8. events: 3 of 5 log entries cover the segment (logs attached to payment_success_rate and its parts: log_deploys, log_provider_status) -> test 3 candidate(s) as hypotheses [r238]
9. holdout: control normal, the change sits where the event applies: the neighbouring segments the event did not touch -0.0% (z -0.0) vs -36.4% inside -> validated: keep as cause [r239]
10. holdout: holdout normal: +0.0% (z +0.0) outside the segment vs -36.4% inside -> refuted: ruled out [r240]
11. holdout: holdout normal: +0.1% (z +0.5) outside the segment vs -36.4% inside -> refuted: ruled out [r241]
12. holdout: the real window: -36.3% (z -44.9); 0 of 5 earlier weeks deviate as much (|z| >= 3.0) the same way -> validated: the deviation is unusual [r242]
13. impact: orders -18.0% per hour: payment_success_rate carries 103% of the change -> where the change came from [r244] [r245]
14. impact: -310.7 payment_successes/h, EUR -21,742/h, EUR -21,742 so far -> severity = cumulative EUR impact [r236] [r246]
15. verdict: SUPPORTED_CAUSE -> stop: explained 100% >= 80%

## Cost of this investigation

22 queries · 0.07 s · 0 LLM calls
