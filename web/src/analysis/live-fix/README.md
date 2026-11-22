# Live Fix

`LiveFix` and `LiveFixProps` are exported from `web/src/analysis/live-fix`. Mount the surface inside the workspace's existing `AgentProvider`, `ReceiptProvider`, and Ice theme. Pass the same `view` and `graph` used by the analysis shell. Pass `incidentId` for an incident entry or `runId` for an agent run. `onSelectRun` can update the shell's deep link. `onOpenIncident` defaults to the existing incident route. Run selection is local when no callback is provided.

For a standalone check, run `make api`, start Vite with `npm --prefix web run dev`, and open `/src/analysis/live-fix/dev.html?fxintro=0`. Pass `incident=INC-0001` or `run=<agent run id>` to open a subject. For a recorded agent presentation, pass `agentrun=<presentation id>` returned by `/demo/start`. That route uses the presentation's snapshot, graph, activity, Ask, and receipts. The dev entry is outside the production Vite entry point.

The left shelf uses activity and run summaries. The right lineage uses observed roles from the selected run. When a recording timestamps every event at the same simulated tick, actual role runtime is unavailable. The live timer measures time observed in the browser, and positive simulation intervals are labeled recorded spans.

Ask uses the existing read-only API. Answers appear when the request completes. Stop waiting aborts the browser request. The server can still finish the work. Conversation context is local to the selected source and subject. Approval controls reuse the existing proposal, operator session, digest, and idempotency implementation.

The layout takes structural cues from the Search Atlas content editor and is inspired by [T3 Code (MIT)](https://github.com/pingdotgg/t3code/tree/11224f63d2a3d444ca1fd1f67cd3ff21c1f5f8a1).
