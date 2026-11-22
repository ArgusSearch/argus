// Reads for the views that `lib/api.ts` does not offer (yet). Same error handling as the main API client.

import { ApiError } from "../lib/api";
import { apiUrl } from "../lib/deployment";
import type { Incident, Note } from "../lib/types";
import { isScorecard } from "./scorecard";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(apiUrl(path), { headers: { accept: "application/json" } });
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

export const views = {
  incidents: () => get<Incident[]>("/incidents"),
  notes: () => get<Note[]>("/notes"),
  benchResults: async () => {
    const card = await get<unknown>("/bench/scorecard");
    if (card === null || isScorecard(card)) return card;
    throw new Error("The API returned an invalid bench scorecard.");
  },
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
