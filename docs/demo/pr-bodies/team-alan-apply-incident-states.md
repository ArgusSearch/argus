# fix(web): incident page shows a skeleton while loading and a plain error with retry

Refs: `docs/demo/issues/web-loading-error-states.md`. File: `web/src/components/IncidentSheet.tsx` only.
Title falls back to "Loading the incident…"; body shows a sheet skeleton, or `ErrorState` with Try again.

## How it was tested

```bash
npm --prefix web run typecheck && npm --prefix web test && npm --prefix web run build
```

Green on this branch (see `docs/demo/HANDOVER.md` for the exact counts). Python checks unchanged (no Python touched).


