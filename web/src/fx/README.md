# Argus Ice: the style layer

Mission Control in a pale-fog, glowing-ice look, switched on per page load from the address bar.
Without the flag nothing of this folder runs: same DOM, same styles, no request for the 3D chunk.
The plan behind it is the scout report `argus-igloo-style` (sections 2 and 3); this note is the part teammates need.

## Try it

```bash
make api                                   # replays the recorded S1 run on port 8000
npm --prefix web run build                 # the API serves web/dist at /
```

| URL | Result |
| --- | --- |
| `/` or `/?fx=0` | today's interface |
| `/?fx=1` (or `fx=ice`) | Argus Ice, light fog |
| `/?fx=night` | the same world after dark |
| `/?demo=1&captions=1&fx=1` | the recording URL: hands-off demo in Argus Ice |
| `&fxq=low\|mid\|high` | fixed quality tier for the 3D scene (default `auto`) |
| `&fxintro=0` | no loader hold, no intro (tests, repeated takes) |
| `&fxdebug=1` | frame rate, worst frame and the scene's quality tier in the bottom-left corner |

The flag is read once and never stored, so other tabs and the end-to-end tests stay on today's interface.

## How it works

- `StyleProvider` (in `main.tsx`) sets `<html data-fx="ice|night">` before the first paint, renders the fixed stage `#fx-stage` behind the app and the loader over it, and loads `fx.css` as its own chunk.
- `tokens.css` remaps the variables of `styles.css` (`--bg`, `--panel`, `--text`, `--alarm`, ...), so every view that uses them follows the look without a change.
- `fx.css` upgrades the existing class names from outside, all under `:root[data-fx]`: glass panels, mono HUD labels with `//` prefixes, brackets on the active tab, the opening choreography, view enter and card cascades.
- `GraphStage` (in `App.tsx`) renders `GraphView` without the flag; with it, it lazy-loads `scene/GraphScene.tsx` (the 3D graph) and falls back to `GraphView` when that file is absent, WebGL2 is missing or the scene throws.
- The opening: the loader holds until `fx.css` and the fonts are in and the graph area has its first frame (`fx:scene-ready`), at least 0.9 s and at most until 2.2 s after navigation start; then it fades, the shell arrives in a short cascade and `fx:intro` tells the scene to materialize.

| File | Role |
| --- | --- |
| `index.ts` | public entry: `StyleProvider`, `GraphStage`, `useFx`, the primitives |
| `flag.ts` | reads `?fx`, `?fxq`, `?fxintro`, `?fxdebug` |
| `StyleProvider.tsx` | theme attribute, stage, loader, the opening |
| `GraphStage.tsx` | drop-in for `GraphView`, scene with fallback and error boundary |
| `events.ts` | the window events shared with the scene (`fx:scene-ready`, `fx:intro`, `fx:quality`, `fx:theme`) |
| `motion.ts` | stagger, CSS time tokens, a cancellable step timeline |
| `tokens.css`, `base.css` | tokens; stage, loader and corner HUD (in the main bundle, inert without the flag) |
| `fx.css` | everything else (its own chunk, only loaded with the flag) |
| `ui/` | the primitives below |
| `scene/` | the 3D graph (another package; do not import from it) |

## Adopting it in a view

Nothing is required.
To check and polish a view:

1. Open it with `?fx=1` and with `?fx=night`.
2. Use the existing variables for every color (`var(--text)`, `var(--panel)`, `var(--line)`, `var(--alarm)`, ...).
   A hard-coded hex or `rgba()` is the usual reason something looks wrong in `ice`.
3. Put content on a surface (`var(--panel)` or `GlassPanel`), not directly on the page background: the stage shows through.
4. Numbers and ids in `var(--mono)`; never animate a number through values it did not have.
5. Optional one-liners from `web/src/fx`, each renders plain content without the flag (below).
6. End-to-end tests stay on the plain URL; a smoke test may open `?fx=1&fxintro=0` and assert `html[data-fx]`.

## Primitives

```tsx
import { Bracket, CornerHud, FxIntro, GlassPanel, HudLabel, TextReveal, useFx } from "../fx";

// a heading whose characters arrive as block cells and resolve to glyphs (plain text without the flag)
<TextReveal as="h2" className="vw-title" text="Metric tree" />

// a `//` label in the HUD type (a plain span without the flag)
<HudLabel>suspects</HudLabel>

// square corner brackets that snap around the focused thing (only the children without the flag)
<Bracket on={focused}>payment_success_rate</Bracket>

// a frosted plate; blur only where the stage behind it moves, at most three at a time
<GlassPanel as="section" className="my-card">...</GlassPanel>

// four labels in the corners of the nearest positioned parent (nothing without the flag)
<CornerHud tl={<HudLabel>argus</HudLabel>} br="0 human actions" />

// a title card in a dawn tint that lifts, then the content cascades in (only the children without the flag)
<FxIntro kicker="morning report" title="While you slept">{report}</FxIntro>

// the flags and the opening's phase ("boot", "intro", "ready")
const { on, theme, phase } = useFx();
```

`Loader` is the ASCII loader the provider shows; it is exported for completeness.

## Budget

- At most three blurred surfaces over the moving stage: the trail, the feed and an open sheet.
  Modals, the toast, the captions and the legend use the opaque `--fx-glass-solid` without a blur.
- No animation library: CSS animations on transform, opacity and short blurs; the reveal (A3) is CSS with one span per character, capped at 48 cells.
- `prefers-reduced-motion` sets every duration token to 1 ms; `styles.css` already stops all animations.
