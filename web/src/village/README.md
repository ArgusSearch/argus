# Argus Village (lane G)

Seven Argus agents at work, one ice igloo each, cut open so you can watch them.
A case travels as a glowing file from igloo to igloo, carried over the snow by the agent that hands it on.
Big bubbles say who is WORKING (with a clock), who NEEDS YOU (the Operator, at an approval) and who is FINISHED.
Click an igloo or a name plate for that agent's tool log.

## Where it shows

- In the workspace (`?fx=1`): lane E's `web/src/fx/workspace/Workspace.tsx` loads `Village.tsx` for the `village` section.
  "Metric map" in the village's header opens the existing visualization page.
- Standalone, for development and captures: `npm run dev`, then `/src/village/lab/index.html`.
- The avatar sheet and the brand-kit exporter: `/src/village/avatars/sheet/index.html`.

## Sources

| Source | What plays |
| --- | --- |
| `s4` | Fault: the ad pacer overspends in DE and FR; the rollback waits for your approval |
| `s4-agent` | The recorded agent investigates S4, asks for approval, and checks the rollback against the untreated twin |
| `s1` | Fault: PayCo payments fail on Android in Germany |
| `s2` | Harmless change: a planned ad push, checked and logged, nobody woken |
| `s5` | The whole market dips (expected, the Market Analyst clears it) and a routing fault hides inside it |
| `live` (default) | The API's C5 stream (`GET /events`, the Stage-2 trail) and, when `GET /agent/health` says enabled, the agent's activity log (`GET /agent/activity`) and proposals (`GET /agent/actions`) |

The recorded sources are tapes in `tapes/`, built from the checked-in recordings and replayed in the browser with no API.
A tape has lane D's presentation-export shape (`fixtures/agent/v1/README.md`): `events`, `activity`, `actions`, and `approve`/`deny` continuations.
Rebuild one with `node web/src/village/tools/build-tapes.mjs <run dir> <id> "<title>" > web/src/village/tapes/<id>.json`; an agent recording directory with `activity.jsonl`, `actions.json` and `approve/` works the same way.
`test/beats.test.ts` fails when a tape drifts from its fixture.

On a tape without a recorded action, approving says so ("nothing runs"); nothing outside the page changes.
With a real agent proposal in Live, Approve and Deny call `POST /agent/actions/{id}/approve|deny` with the proposal's digest.

## URL options

`?village=s1|s2|metric|s4|s4-agent|s5|live`, `?village2d=1` (the 2D stage), `?vspeed=0.5|1|2|4`, `?vat=<seconds>` (start there), `fxq=low|mid|high`.
`window.__villagePlayer` is the clock (`seek`, `setPlaying`, `setSpeed`) for headless captures.
In the 3D scene, `window.__village.step(seconds)` advances the scene and playback clocks by one frame for recording.
`window.__village.release()` returns both clocks to browser playback.

## Roles

| Role | Agent | Tools it runs |
| --- | --- | --- |
| Watcher | B.E.A.C.O.N. | ticks, `check_freshness`, anomalies, the incident lifecycle |
| Cartographer | G.R.I.D. | edge tests, `check_identities`, `decompose_formula` |
| Detective | S.L.E.U.T.H. | `list_events`, `mix_rate_split`, `segment_search`, `get_series`, anything unknown |
| Market Analyst | T.I.C.K.E.R. | `check_control_group` |
| Skeptic | D.O.U.B.T. | `holdout_check`, `placebo_test`, skeptic steps, the agent's gate |
| Narrator | S.C.R.I.B.E. | impact, `counterfactual_impact`, the verdict, filing, notes, reports |
| Operator | L.E.V.E.R. | proposals, decisions, the action and its effect check |

`roleOfTool` in `beats.ts` holds the mapping; the names live in `avatars/personas.ts`.

## Avatars for other lanes

```tsx
import { AgentAvatar } from "../village/avatars";
<AgentAvatar role="operator" status="waiting" size={64} nameplate />
```

`status`: `idle`, `working`, `waiting` (coral "!" badge), `done` (green check), `sleeping`.
The bodies are `bot-avatars` (MIT, libraries.dev/bots); armor, names and colors are ours.
Each agent wears a role costume over the armor (`avatars/costumes.ts`, two looks per role, our own vector shapes); look 1 is the default everywhere (`defaultLook`), and props stay close to the avatar's box so it can sit next to text.
PNG sheets and single avatars: `web/public/village/avatars/` and the brand kit.

## Files

`types.ts` (tape and lane A mirror), `beats.ts` (tape to beats), `timeline.ts` (beats on a clock, the village at time t), `player.ts` (the clock), `source.ts` (tapes and live), `ArgusVillage.tsx`, `Overlay.tsx`, `Village2D.tsx`, `scene/` (three.js: igloos, rooms, bots, world, engine), `avatars/`.
