# [copy] consistent English on screen: one term per thing, readable verdicts, no internal ids in prose

Labels: web, narrator, copy · Checked on main (f35b00a) in replay at 1920x1080 and 390 wide, 2026-11-21

Terms the page should use everywhere: "incident", "note", "didn't wake you", "receipt", "re-run", "ruled out";
verdicts as readable labels ("Supported cause", "Data issue", ...) without changing the API values.

## Fixed in string-only branches (web, one component each)

| Branch | File | Before | After |
| --- | --- | --- | --- |
| `team/alan/copy-ticker` | `Ticker.tsx` | "held back" | "didn't wake you" (same word as the feed tab) |
| `team/alan/copy-feed` | `Feed.tsx` | "Data issue · held back" | "Data issue · didn't wake you" |
| `team/alan/copy-trail` | `Trail.tsx` | "Drop playbook" / "Spike playbook" | "Playbook for a drop" / "Playbook for a spike" |
| `team/alan/copy-incident` | `IncidentSheet.tsx` | "Copy report (Markdown)" | "Copy as Markdown" (as in "While you slept") |

## Needs a code change, not only strings (web, owner `argus-api`)

1. Trail verdict card prints the raw API value `SUPPORTED_CAUSE` (`Trail.tsx`, step kind `verdict`, from `step.result`).
   Map it with a verdict label helper (the challenge screens use `verdictLabel()` in `web/src/challenge/model.ts`;
   a shared one in `web/src/lib/format.ts` would serve both).
2. Feed and incident pills use `verdict.replace("_", " ")`; with the uppercase pill style it reads "SUPPORTED CAUSE".
   Fine on screen, but use the same label helper so copy and screen readers get "Supported cause".

## API and narrator strings (owner: narrator / API lanes)

3. Digest: "Opened | 0 anomalys" (plural of anomaly is "anomalies"). `GET /digest`, line `opened`.
4. Digest label "Held back" next to the detail "didn't wake you": use one term ("Didn't wake you").
5. Incident title repeats the provider: "Payment success rate -33.6% in android / DE / PayCo: PayCo: elevated decline
   rates for Android SDK payments in Germany". Drop the second "PayCo:" (the log line already names it).
6. Segment order differs inside one sheet: the title says "android / DE / PayCo", the chips and the prose say
   "DE · android · PayCo". Use the `DIM_ORDER` of `web/src/lib/format.ts` (country, platform, provider) in the narrator too.
7. Trail impact step: "-280.0 payment_successes/h, EUR -19,717/h, EUR -19,717 so far": metric ids in prose and
   "EUR" where every other screen writes "€". Suggest "-280 payment successes per hour, -€19,717 per hour, -€19,717 so far".
8. Trail verdict step foot: "stop: explained 100% >= 80%" reads like code. Suggest "Stopped: 100% of the change explained (needs 80%)".
9. S3 data-issue note: "fact_orders_hourly 23:00 is only 55% delivered at 01:00" names a table; suggest "the orders
   feed for 23:00 is only 55% delivered at 01:00".

No German, no "lane", "fixture" or "C5" found on screen. "wiggle" is the app's own term and is explained in the legend.
