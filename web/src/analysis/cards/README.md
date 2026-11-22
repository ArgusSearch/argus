# Analysis cards

Import the components and types from `web/src/analysis/cards/index.ts`. Supply the active stream or replay run's scoped data and evidence links from the surrounding analysis page. The card components take props and can render independently.

| Component | Input and display |
| --- | --- |
| `MetricBarsCard` | One unit across signed or unsigned bars. An optional headline and change have their own units and a named comparison basis. Hatched bars carry a legend label. |
| `TickRingCard` | Observed fraction from 0 to 1, with an optional labeled benchmark in the same unit and scope. |
| `MetricTrendCard` | Timestamped observations, optional expected values and bounds, and one dated event. Set `maxGapMs` to the source cadence to connect successive points. The default plots isolated samples. The event uses a focusable tooltip and the chart has a data table. |
| `DistributionCard` | Mutually exclusive, whole-number counts and a total for the same population. The ring renders only when the counts reconcile to a positive total. |

`null` represents a missing value. A fraction uses `share`, a relative percent uses `pct`, and a percentage-point difference uses `pp`. The anomaly adapters match observations by metric and exact scope. Pass events and current incident evidence from the same stream and cursor.

The Vite dev route is `/src/analysis/cards/preview.html`. It reads Argus through the standard Vite API proxy. From the repository root, start the recorded S1 API in one terminal and the web dev server in another.

```sh
uv run argus api --replay fixtures --port 8000
```

```sh
npm --prefix web run dev
```

For a stable view of the completed recording on that local API, pause it and advance to its final cursor.

```sh
curl -fsS localhost:8000/replay -H 'Content-Type: application/json' -d '{"action":"pause"}'
curl -fsS localhost:8000/replay -H 'Content-Type: application/json' -d '{"action":"end"}'
```

The S1 preview uses the observed shop-wide payment rate, the watcher’s expected range, nested segment changes, incident states, and an investigation receipt for the refuted Android release. It renders the single observed time bucket as a point. The logged release timestamp is shown separately on the time axis.
