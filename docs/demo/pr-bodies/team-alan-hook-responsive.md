# hook: import the responsive layout once in main.tsx

One line in `web/src/main.tsx` (owned by `argus-api`): `import "./ui/responsive.css";` after `styles.css`.
Announce in the chat before pushing (section 7, rule 2). Depends on `team/alan/polish` (the CSS file).

`web/src/ui/responsive.css` covers 1920x1080 (projector tier: header, ticker, rail and trail zoomed 1.12, wider rail;
the graph is never zoomed), 1440x900 (unchanged), 1280x720 (slimmer bars), 768 (one column, page scrolls) and 390.
Demo mode can opt out of the projector tier with `data-demo` on `<html>`.

## How it was tested

```bash
npm --prefix web run typecheck && npm --prefix web test && npm --prefix web run build
```

Green on this branch (see `docs/demo/HANDOVER.md` for the exact counts). Python checks unchanged (no Python touched).

Screenshots: `docs/demo/screenshots/mc-*.png` (before: `before-*.png`). Horizontal scroll at 768 went from 497 px to 0, at 390 from 875 px to 0.
