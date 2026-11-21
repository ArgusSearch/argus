# web (lane U)

Mission Control lives here: Vite + React + TypeScript, React Flow for the live graph.

Build against the contracts, not against the Python code:

- Event stream: `GET /events` (Server-Sent Events, one `Event` per message, schema in `contracts/c5_events.schema.json`).
- REST routes: listed in `contracts/c5_events.schema.json` under `routes`, or `GET /routes` on a running API.
- Types: generate TypeScript from the JSON Schemas in `contracts/` (for example with `json-schema-to-typescript`).
- Offline: `make api` replays `fixtures/events.jsonl` through the same SSE code path as live mode.
- Live: `make demo` runs Argus over a fresh S1 world and streams the investigation as it happens.

The UI never computes numbers itself: every number it shows comes from the API with a receipt id.
