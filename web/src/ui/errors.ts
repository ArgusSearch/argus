// Plain-English explanations for failed API calls: no status codes without words, no raw JSON, no stack traces.

import { ApiError } from "../lib/api";
import { publicApi } from "../lib/deployment";

export interface Explained {
  /** One short line: what went wrong. */
  title: string;
  /** What the person can do about it. */
  detail: string;
  /** Whether trying the same request again can help. */
  retry: boolean;
}

/** The API's own message, unless it is empty, JSON-ish or a bare status code. */
function readable(message: string): string | null {
  const text = message.trim();
  if (!text || /^[[{]/.test(text) || text.includes("[object ") || /^\d{3}$/.test(text)) return null;
  return text.endsWith(".") ? text : `${text}.`;
}

function statusOf(error: unknown): number | null {
  if (error instanceof ApiError) return error.status;
  // api.report() throws Error("<status>")
  if (error instanceof Error && /^\d{3}$/.test(error.message.trim())) return Number(error.message.trim());
  return null;
}

export function explainError(error: unknown, route?: string): Explained {
  const where = route ? ` ${route}` : "";
  const status = statusOf(error);
  const said = error instanceof ApiError ? readable(error.message) : null;

  if (status === null) {
    // fetch() rejects with a TypeError when nothing answers at all
    if (error instanceof TypeError || (error instanceof Error && /fetch|network|load failed/i.test(error.message))) {
      return {
        title: "Can't reach the Argus API",
        detail: publicApi ? "Try again in a moment." : "Start the API, then try again.",
        retry: true,
      };
    }
    const message = error instanceof Error ? readable(error.message) : null;
    return { title: "Something went wrong", detail: message ?? "Try again in a moment.", retry: true };
  }
  if (status === 409 && route?.includes("/rerun")) {
    return {
      title: "Receipt re-runs need live mode",
      detail: publicApi
        ? "Open Mission Control to re-run receipts from the live Shop."
        : "Open a live source to re-run receipts.",
      retry: false,
    };
  }
  if (status === 409) {
    return { title: "Not available in this mode", detail: said ?? (publicApi ? "Return to Mission Control and try again." : "Open a live source and try again."), retry: false };
  }
  if (status === 501) {
    return { title: "Not built yet", detail: `The API does not serve${where || " this"} yet.`, retry: false };
  }
  if (status === 404) {
    return { title: "Not found", detail: said ?? `The API has nothing at${where || " this address"}.`, retry: false };
  }
  if (status >= 500) {
    return {
      title: "The API hit an error",
      detail: `${route ?? "The request"} answered ${status}. Try again; if it keeps failing, check the terminal that runs the API.`,
      retry: true,
    };
  }
  return { title: `The API said no (${status})`, detail: said ?? "Try again in a moment.", retry: true };
}
