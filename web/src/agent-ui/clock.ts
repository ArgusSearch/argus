// How long a run has been working, on the wall clock of this page (the records carry simulated time, which stands
// still within an hour). A run is timed from the moment this page first saw it live until it saw it finish.

/** "12s", "1m 05s", "1h 02m" (T3 Code's elapsed format). */
export function formatElapsed(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const minutes = Math.floor(seconds / 60);
  if (minutes === 0) return `${seconds}s`;
  const hours = Math.floor(minutes / 60);
  if (hours === 0) return `${minutes}m ${String(seconds % 60).padStart(2, "0")}s`;
  return `${hours}h ${String(minutes % 60).padStart(2, "0")}m`;
}

interface Span {
  start: number;
  end: number | null;
}

/** Start and end times per run key; one clock for the page, so leaving and coming back keeps the timer. */
export class RunClock {
  private spans = new Map<string, Span>();

  /** Notes what the page sees now: a live run starts its timer, a run seen ending stops it. */
  observe(key: string, live: boolean, now: number) {
    const span = this.spans.get(key);
    if (live) {
      if (!span) this.spans.set(key, { start: now, end: null });
      else if (span.end !== null) span.end = null; // came back to life (a restarted presentation)
    } else if (span && span.end === null) {
      span.end = now;
    }
  }

  /** Milliseconds worked, or null for a run this page never saw live. */
  elapsed(key: string, now: number): number | null {
    const span = this.spans.get(key);
    if (!span) return null;
    return (span.end ?? now) - span.start;
  }

  running(key: string): boolean {
    return this.spans.get(key)?.end === null;
  }

  forget() {
    this.spans.clear();
  }
}

export const runClock = new RunClock();
