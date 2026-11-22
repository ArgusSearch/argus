// Reads for the views that `lib/api.ts` does not offer (yet). Same rules: relative paths, errors as ApiError.

import { ApiError } from "../lib/api";
import type { Incident, Note } from "../lib/types";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { accept: "application/json" } });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

/** A row of the API's route table (GET /routes): routes owned by other lanes answer 501 while they are stubs. */
export interface RouteInfo {
  method: string;
  path: string;
  status: string;
}

/** Whether the route table marks a route as a stub; an unreadable table marks nothing. */
export function isStub(routes: RouteInfo[] | null, method: string, path: string): boolean {
  return routes?.some((r) => r.method === method && r.path === path && r.status === "stub") ?? false;
}

let table: Promise<RouteInfo[] | null> | null = null;

/** The route table, read once per page load; null when it cannot be read. */
function routeTable(): Promise<RouteInfo[] | null> {
  table ??= get<unknown>("/routes").then(
    (rows) => (Array.isArray(rows) ? (rows as RouteInfo[]) : null),
    () => null,
  );
  return table;
}

/**
 * Reads a route unless the route table says it is a stub: the 501 would end the same way (the caller's
 * fallback), but the browser logs every failed request as a console error.
 */
async function getServed<T>(path: string): Promise<T> {
  if (isStub(await routeTable(), "GET", path)) throw new ApiError(501, `${path} is not built yet`);
  return get<T>(path);
}

export const views = {
  incidents: () => get<Incident[]>("/incidents"),
  notes: () => get<Note[]>("/notes"),
  benchResults: () => getServed<unknown>("/bench/results"),
};

/** A plain-English line for a failed read, for the view's error state. */
export function explain(error: unknown, what: string): string {
  if (error instanceof ApiError) {
    if (error.status === 501) return `${what} is not served by this API yet.`;
    if (error.status === 404) return `${what} was not found.`;
    return `${what} could not be loaded (${error.status}): ${error.message}`;
  }
  return `${what} could not be loaded: the API did not answer. Is \`make api\` running?`;
}
