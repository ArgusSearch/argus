# hook: mount the blind challenge screens around App in main.tsx

Three lines in `web/src/main.tsx` (owned by `argus-api`): import `ChallengeGate` and wrap `<App />` in it.
Without `?challenge` in the URL the gate renders `<App />` untouched; the screens load lazily (own 26 kB chunk).
It does not touch `App.tsx`, so it does not collide with Youssef's `ViewHost` hook (PR #25).
Announce in the chat before pushing. Depends on `team/alan/polish`.

## How it was tested

```bash
npm --prefix web run typecheck && npm --prefix web test && npm --prefix web run build
```

Green on this branch (see `docs/demo/HANDOVER.md` for the exact counts). Python checks unchanged (no Python touched).

Screens: `/?challenge` (pick and seal), `/?challenge=run` (Mission Control with the commitment banner), `/?challenge=reveal`, `/?challenge=verify&c=<hash>` (phone). Screenshots: `docs/demo/screenshots/challenge-*.png`.
