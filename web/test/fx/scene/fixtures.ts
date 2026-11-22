// The recorded runs the scene tests replay: fixtures/ (S1) and fixtures/<scenario>/.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { ArgusEvent, Graph } from "../../../src/lib/types";

const root = (path: string) => fileURLToPath(new URL(`../../../../fixtures/${path}`, import.meta.url));

export function loadGraph(scenario = ""): Graph {
  return JSON.parse(readFileSync(root(`${scenario ? `${scenario}/` : ""}graph.json`), "utf8")) as Graph;
}

export function loadEvents(scenario = ""): ArgusEvent[] {
  return readFileSync(root(`${scenario ? `${scenario}/` : ""}events.jsonl`), "utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line) as ArgusEvent);
}
