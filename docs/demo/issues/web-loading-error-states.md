# [web] plain loading, empty and error states in existing components

Labels: web, polish · Primitives: `web/src/ui/` (Alan) · One branch per component (section 7, rule 3)

Today a slow or failed request shows a bare "Loading…" or the raw API message, the graph area is blank until
`GET /graph` answers, and an empty feed tab says "Nothing here yet." Each item below is one small branch that
only swaps those spots for the shared primitives (`Skeleton`, `ErrorState`, `EmptyState`, `OfflineBanner`) and
`explainError()` (plain English per status, never raw JSON; vitest in `web/src/ui/errors.test.ts`).

| Branch | File | Change |
| --- | --- | --- |
| `team/alan/apply-app-states` | `web/src/App.tsx` | `OfflineBanner` replaces the red "API is offline" banner (connecting, not running, lost with a retry clock, Reload); graph skeleton while `graph` is null; fetch the graph once the stream opens if it is still missing |
| `team/alan/apply-feed-empty` | `web/src/components/Feed.tsx` | per-tab empty states, e.g. "No incidents. Argus is watching 27 metrics." |
| `team/alan/apply-receipts-states` | `web/src/components/Receipts.tsx` | skeleton while the receipt loads, `ErrorState` with retry, and the replay 409 on re-run reads "Receipt re-runs need live mode. ... Start Argus live with make demo to re-run receipts." |
| `team/alan/apply-digest-states` | `web/src/components/Overlays.tsx` (`DigestModal`) | skeleton and `ErrorState` with retry for `GET /digest` |
| `team/alan/apply-incident-states` | `web/src/components/IncidentSheet.tsx` | sheet skeleton and `ErrorState` with retry for `GET /incidents/{id}` |

Acceptance (checked with Playwright, see `docs/demo/HANDOVER.md`): start the page with the API stopped, then
start it: no blank screen, no raw JSON, no stack trace; the page recovers without a reload.
