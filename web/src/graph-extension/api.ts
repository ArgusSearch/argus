// REST client of the graph extension.

import { ApiError } from "../lib/api";
import { apiUrl } from "../lib/deployment";
import type { ExtensionState, MetricDefinition, PlacementResult } from "./types";

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(apiUrl(path), init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const extensionApi = {
  state: () => json<ExtensionState>("/graph/metrics"),
  placement: (name: string) => json<PlacementResult>(`/graph/metrics/${encodeURIComponent(name)}`),
  place: (metric: MetricDefinition) =>
    json<PlacementResult>("/graph/metrics", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(metric),
    }),
};
