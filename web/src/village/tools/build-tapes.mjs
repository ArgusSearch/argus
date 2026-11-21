#!/usr/bin/env node
// Builds a village tape from a recorded run directory: C5 events (events.jsonl), the C3 graph (graph.json), the
// C4 incidents (incidents.json) and, when the run is an agent recording in lane D's presentation layout
// (fixtures/agent/v1/README.md), its activity.jsonl, actions.json and approve/ and deny/ continuations.
// Step payloads are trimmed to what the village shows; numbers stay as the recording rendered them.
//
//   node web/src/village/tools/build-tapes.mjs <run dir> <scenario> "<title>" > web/src/village/tapes/<scenario>.json
//
// The checked-in tapes come from the S1 and S4 recordings:
//   node web/src/village/tools/build-tapes.mjs fixtures s1 "S1 · PayCo payments fail on Android in Germany"
//   node web/src/village/tools/build-tapes.mjs fixtures/s4 s4 "S4 · The ad pacer overspends in DE and FR"

import { existsSync, readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";

const [dir, scenario, title] = process.argv.slice(2);
if (!dir || !scenario || !title) {
  console.error('usage: build-tapes.mjs <run dir> <scenario> "<title>"');
  process.exit(2);
}

const read = (path) => (existsSync(path) ? readFileSync(path, "utf8") : null);
const jsonl = (path) =>
  (read(path) ?? "")
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
const json = (path, fallback) => {
  const text = read(path);
  return text === null ? fallback : JSON.parse(text);
};

/** Only the step data the village reads: the tested event, the located path, the onset, the market verdict. */
function trimStep(step) {
  const keep = {};
  const d = step.data ?? {};
  if (d.event) keep.event = { log: d.event.log, ref: d.event.ref, description: d.event.description, scope: d.event.scope };
  if (typeof d.node === "string") keep.node = d.node;
  if (typeof d.onset === "string") keep.onset = d.onset;
  if (d.market_control) keep.market_control = { verdict: d.market_control.verdict, reason: d.market_control.reason };
  if (typeof d.explained_share === "number") keep.explained_share = d.explained_share;
  return { ...step, data: keep };
}

function trimEvent(e) {
  switch (e.type) {
    case "tick":
      return {
        seq: e.seq,
        sim_ts: e.sim_ts,
        type: e.type,
        payload: {
          as_of: e.payload.as_of,
          hour: e.payload.hour,
          freshness: [],
          scored_nodes: e.payload.scored_nodes,
          pending_nodes: e.payload.pending_nodes,
          max_abs_z: e.payload.max_abs_z,
          open_incidents: e.payload.open_incidents,
        },
      };
    case "edge_status":
      return {
        ...e,
        payload: {
          ...e.payload,
          result: { ...e.payload.result, receipts: e.payload.result.receipts.slice(0, 3) },
        },
      };
    case "investigation_step":
      return { ...e, payload: { ...e.payload, step: trimStep(e.payload.step) } };
    case "attention":
    case "bench_progress":
    case "challenge_state":
      return null;
    default:
      return e;
  }
}

function part(path) {
  return {
    events: jsonl(join(path, "events.jsonl")).map(trimEvent).filter(Boolean),
    activity: jsonl(join(path, "activity.jsonl")),
    actions: json(join(path, "actions.json"), []),
  };
}

const root = resolve(dir);
const graph = json(join(root, "graph.json"), { nodes: [] });
const incidentsRaw = json(join(root, "incidents.json"), []);
const incidents = (Array.isArray(incidentsRaw) ? incidentsRaw : Object.values(incidentsRaw)).map((i) => ({
  id: i.id,
  title: i.title,
  segment: i.segment ?? {},
  suggested_action: i.findings?.suggested_action ?? null,
}));
const continuations = {};
for (const decision of ["approve", "deny"]) {
  if (existsSync(join(root, decision))) continuations[decision] = part(join(root, decision));
}

const repo = resolve(new URL("../../../../", import.meta.url).pathname);
const tape = {
  version: 1,
  scenario,
  title,
  source: relative(repo, root) || ".",
  labels: Object.fromEntries(graph.nodes.map((n) => [n.id, n.label])),
  incidents,
  ...part(root),
  continuations,
};
process.stdout.write(`${JSON.stringify(tape)}\n`);
