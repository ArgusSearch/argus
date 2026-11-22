# web/src/fx/scene: the 3D metric graph

The metric graph as an ice scene in Three.js, behind the `fx` flag of the style layer (`web/src/fx`).
Nothing outside `web/src/fx` imports from this folder; the style layer loads `GraphScene.tsx` lazily, so the Three.js chunk is never requested without the flag.

## Props

```tsx
import GraphScene from "./scene/GraphScene"; // default export, load it with React.lazy

<GraphScene graph={graph} view={view} onSelectNode={setNodeId} />                    // the graph's own view
<GraphScene graph={graph} view={view} onSelectNode={setNodeId} variant="preview" />  // dashboard card
```

| Prop | Meaning |
| --- | --- |
| `graph` | C3 graph from `GET /graph`; a later version may add metrics, which then freeze in |
| `view` | the folded C5 stream (`lib/store.ts`) |
| `onSelectNode` | called with the metric or log id when a block is clicked (opens the NodeSheet) |
| `variant` | `"full"` (default) or `"preview"` |

Both variants render one element that fills its parent (`position: absolute; inset: 0`), so the parent needs a size and `position: relative`.
That element is the safe rectangle the camera frames the graph in, and it takes hover and clicks.

- **full:** the canvas goes into `#fx-stage` (the style layer's full-window stage) and the graph is framed inside the mount's rectangle; without `#fx-stage` (the lab) the canvas sits inside the mount.
  It plays the materialize intro on the layer's `fx:intro` cue, flies the camera through the investigation, and reports `fx:scene-ready` and `fx:quality`.
- **preview:** the canvas stays inside the mount (a card of any size), the intro is a short 1.2 s freeze-in, no layer events are sent or awaited, and the camera frames the affected path of the open incident (the whole graph when there is none).
  Only the north-star metrics and the path are labelled.

## What the scene shows

- North-star metrics are large blocks with large labels; the other metrics are small and quiet (full label on hover); logs sit back and low.
- Block light carries the state, with the same rules as the 2D graph (`model.ts`, pinned by `web/test/fx/scene/model.test.ts`): watch for a wiggle, red and cracked for an alarm or root cause, green when resolved, blue while Argus checks it.
- During an investigation the camera frames what Argus has touched, a numbered trace walks the checked metrics and logs with the trail's step numbers, and the logs it rules out dim.
- The affected path (`incidentPath` in `model.ts`): the anomaly, everything its formulas move downstream, and the evidence that held; it burns warm while the rest of the graph recedes.
- Hourly tick, alarm and freeze-in pulses run over the ground; a test result runs as a pulse along its edge.

## Events (report section 3.4, I7)

| Event | Direction | |
| --- | --- | --- |
| `fx:scene-ready` | sent (full only) | first frame is on screen |
| `fx:intro` `{ duration }` | received (full only) | start the intro; without it the scene starts on its own after 1.5 s |
| `fx:quality` `{ tier, pixelRatio, fps }` | sent (full only) | on every quality change |
| `fx:theme` | received | re-read the tokens (`data-fx` changes are also observed) |

## Quality

`?fxq=high|mid|low` fixes a tier; the default `auto` starts at high and, below 55 fps, first drops bloom, then resolution in steps of 0.1 down to 0.7 (`quality.ts`).
Rendering stops while the tab or the mount is hidden; unmounting frees the WebGL context.
`?fxdebug=1` (or the lab) publishes frame statistics on `window.__fxScene`.

## Lab

`make api` and `npm --prefix web run dev`, then open `http://localhost:5173/fx-lab.html`: the scene full-window against the running API, with replay controls, theme, quality, a replay of the intro, the preview card (`?preview=1`) and "learn a metric" to see a freeze-in.
