// Arrow-up recalls an earlier question, the way T3 Code's composer does (composerPromptHistory, pingdotgg/t3code,
// MIT; rewritten for Argus): only from an empty box or from a recalled question left as it was, so a draft is
// never overwritten; arrow-down walks forward and past the newest clears the box. The questions survive a reload in
// this browser.

const KEY = "argus.ask.history.v1";
const KEEP = 50;

export interface HistoryPosition {
  readonly index: number;
  readonly recalled: string;
}

export interface HistoryStep {
  readonly position: HistoryPosition | null;
  readonly prompt: string;
}

/** The history with a sent question added: trimmed, empty ones skipped, a repeat of the newest kept once. */
export function remember(entries: readonly string[], prompt: string, keep = KEEP): string[] {
  const p = prompt.trim();
  if (!p) return [...entries];
  const next = entries[entries.length - 1] === p ? [...entries] : [...entries, p];
  return next.slice(-keep);
}

function activeIndex(entries: readonly string[], position: HistoryPosition | null, current: string): number {
  if (!position || position.recalled !== current) return -1;
  if (entries[position.index] === position.recalled) return position.index;
  return entries.lastIndexOf(position.recalled);
}

export function step(input: {
  direction: "backward" | "forward";
  entries: readonly string[];
  position: HistoryPosition | null;
  current: string;
}): HistoryStep | null {
  const { entries, position, current } = input;
  const active = activeIndex(entries, position, current);
  if (input.direction === "backward") {
    if (active < 0 && current.length > 0) return null; // a draft: leave it alone
    const index = active < 0 ? entries.length - 1 : active - 1;
    if (index < 0) return null;
    return { position: { index, recalled: entries[index] }, prompt: entries[index] };
  }
  if (active < 0) return null;
  const index = active + 1;
  if (index >= entries.length) return { position: null, prompt: "" };
  return { position: { index, recalled: entries[index] }, prompt: entries[index] };
}

/** Whether the caret sits on the box's first line (for up) or last line (for down), with nothing selected. */
export function caretOnEdge(value: string, start: number, end: number, direction: "backward" | "forward"): boolean {
  if (start !== end) return false;
  return direction === "backward" ? !value.slice(0, start).includes("\n") : !value.slice(end).includes("\n");
}

export function loadHistory(): string[] {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string").slice(-KEEP) : [];
  } catch {
    return [];
  }
}

export function saveHistory(entries: readonly string[]) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(entries.slice(-KEEP)));
  } catch {
    /* private mode: the history holds for this page load */
  }
}
