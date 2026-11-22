# Argus analytics

Use `AnalyticsPanels` with the active `RunView`, graph, and incident details from the same stream. The controlled `query` accepts the analysis shell’s `metric`, `segment`, and `period` fields. Connect `onPeriodChange` to the shell’s query update and `segmentHref` to its Segments destination. Pass `section="history"` or `section="distribution"` for single-panel destinations. `ShopMetrics` reads the existing whole-shop health checks. Mount these components inside the Ice workspace and its `ReceiptProvider`.

For a local check, run the API with `make api` at the project root and Vite with `npm run dev` in `web/`. Open `/src/analysis/analytics/dev.html` on the Vite server. In the S1 replay, pause then end through the existing replay controls or `POST /replay` to inspect the finished run.

| Surface | Source |
| --- | --- |
| Historical Metrics | Exact-scope measurements from `/events` anomaly openings and single-hour incident findings. Optional raw series need a source that identifies the metric and scope. Dates use the active stream clock in UTC. |
| Incident and release markers | Incident lifecycle and dated deploy/release evidence from `/incidents` or the run’s demo snapshot. |
| Country Distribution | The latest matching incident’s `segment_search` path. Parent volume shares describe nested scopes. Change is relative to the expected baseline. Receipt links open the underlying API queries. |
| Shop Metrics | Whole-shop operational checks from the active stream and `/graph`. Gauges show reported counts and omit the fill when the denominator is absent. |

S1 has one whole-shop payment success sample. The selected period filters the retained evidence. Full-period business history, country totals, and raw country volumes require an aggregate read contract.
