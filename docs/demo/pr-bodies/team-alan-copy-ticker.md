# fix(web): ticker says "didn't wake you" like the feed tab instead of "held back"

String only, `web/src/components/Ticker.tsx`. Refs: `docs/demo/issues/web-copy.md`.

## How it was tested

```bash
npm --prefix web run typecheck && npm --prefix web test && npm --prefix web run build
```

Green on this branch (see `docs/demo/HANDOVER.md` for the exact counts). Python checks unchanged (no Python touched).


