# SUPPORTED CAUSE · Payment success rate down in android / DE / PayCo

INC-0001 · state resolved · opened 2026-11-21 18:00 UTC · as_of 2026-11-21 20:00

## What happened

Payment success rate moved -2.04% [r225] against its expectation (observed 0.9290 [r225], expected 0.9483 [r225]).
Inside android / DE / PayCo, payment success rate moved -33.6% [r236]; this segment explains 100% of the deviation.
Evidence: PayCo: elevated decline rates for Android SDK payments in Germany (log_provider_status `ps_payco_degraded`, 2026-11-21 17:53) [r238].

## Impact

-280.0 orders per hour [r236], EUR -19,717 GMV per hour [r243], EUR -19,717 so far over 1 h [r243].

## Where the change came from (LMDI on orders, exact)

| factor | share of the change |
| --- | --- |
| payment_success_rate | +98% [r242] |
| sessions | +19% [r241] |
| cart_rate | -13% [r241] |
| checkout_rate | -11% [r241] |
| view_rate | +3% [r241] |
| attempt_rate | +3% [r242] |

## Ruled out

- checkout-service 1.2.6 (all users): predicted "everything in the event's scope moves, not only android / DE / PayCo"; refuted (holdout normal) [r239]
- android-app 8.3.0 rolled out to 100% of Android users in all countries: predicted "everything in the event's scope moves, not only android / DE / PayCo"; refuted (holdout normal) [r240]

## Still uncertain

- Whether the fault is inside PayCo or in our PayCo integration.
- 0% of the deviation is outside the root segment.

## Suggested action (needs human approval)

Route android-DE payments from PayCo to CardHub until PayCo recovers.

## Lifecycle

- 2026-11-21 18:00 open: an_0001
- 2026-11-21 18:00 investigating: fixed opening started
- 2026-11-21 18:00 explained: SUPPORTED_CAUSE
- 2026-11-22 00:00 monitoring: root segment z -0.3 at 2026-11-22 00:00
- 2026-11-22 02:00 resolved: 3 consecutive normal hours
- severity (cumulative EUR impact while open): EUR 99,647

## Investigation trail

1. freshness: all source tables complete -> continue [r226]
2. identities: identities hold -> continue [r227] [r228]
3. calendar: no planned event in the window -> continue: not an expected change [r229]
4. decompose: payment_success_rate has no formula children -> localise payment_success_rate directly
5. segment: platform=android AND country=DE AND provider=PayCo explains 100% of the deviation (-33.6%) -> root segment android / DE / PayCo [r230] [r231] [r232] [r233] [r234] [r235] [r236]
6. segment: root segment deviates since 2026-11-21 18:00 -> align evidence with the root onset [r237]
7. events: 3 of 5 log entries cover the segment -> test 3 candidate(s) [r238]
8. holdout: holdout normal: +0.2% (z +1.0) outside the segment vs -33.6% inside -> ruled out [r239]
9. holdout: the event's scope is exactly the anomalous segment: nothing to hold out -> keep as cause
10. holdout: holdout normal: -0.2% (z -0.4) outside the segment vs -33.6% inside -> ruled out [r240]
11. impact: orders -16.2% per hour: payment_success_rate carries 98% of the change -> where the change came from [r241] [r242]
12. impact: -280.0 payment_successes/h, EUR -19,717/h, EUR -19,717 so far -> severity = cumulative EUR impact [r236] [r243]
13. verdict: SUPPORTED_CAUSE -> stop: explained 100% >= 80%

## Cost of this investigation

19 queries · 0.06 s · 0 LLM calls
