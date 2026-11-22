// REST client of the graph extension.

import { ApiError } from "../lib/api";
import { apiUrl, publicApi } from "../lib/deployment";
import type { ExtensionState, MetricDefinition, PlacementResult } from "./types";

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(apiUrl(path), {
    ...(publicApi && { credentials: "include" }),
    ...init,
  });
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

let session: Promise<{ csrf_token: string }> | null = null;

function operatorSession() {
  session ??= json<{ csrf_token: string }>("/agent/operator/session", { method: "POST" }).catch((error: unknown) => {
    session = null;
    throw error;
  });
  return session;
}

async function place(metric: MetricDefinition): Promise<PlacementResult> {
  const send = (csrf?: string) => json<PlacementResult>("/graph/metrics", {
    method: "POST",
    headers: { "content-type": "application/json", ...(csrf && { "X-Argus-CSRF": csrf }) },
    body: JSON.stringify(metric),
  });
  if (!publicApi) return send();
  const active = operatorSession();
  try {
    return await send((await active).csrf_token);
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 403) throw error;
    if (session === active) session = null;
    return send((await operatorSession()).csrf_token);
  }
}

export const extensionApi = {
  state: () => json<ExtensionState>("/graph/metrics"),
  placement: (name: string) => json<PlacementResult>(`/graph/metrics/${encodeURIComponent(name)}`),
  place,
};
